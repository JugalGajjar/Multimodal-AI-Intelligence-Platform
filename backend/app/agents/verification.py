"""Score an answer's groundedness against its cited context.

The LLM decomposes the answer into atomic claims, labels each
`supported | unsupported | uncertain`, and we compute a score in [0, 1]:
supported=1.0, uncertain=0.5, unsupported=0.0. Score maps to a verdict via
thresholds in settings.

Skipped (best-effort) when disabled, when there's no context, or on any
upstream error — so chat never fails because verification couldn't run.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.config import settings
from app.rag.graph_expansion import GraphFact
from app.rag.groq_chat import GroqChatError, chat_completion
from app.rag.prompts import STRICT_REFUSAL_MESSAGE
from app.rag.retrieval import RetrievedChunk
from app.rag.tavily import WebResult

log = logging.getLogger("mmap.agents.verification")

Verdict = Literal["verified", "partial", "unsupported", "skipped"]


@dataclass(frozen=True)
class ClaimVerdict:
    text: str
    support: str  # "supported" | "unsupported" | "uncertain"
    evidence: str = ""


@dataclass(frozen=True)
class VerificationResult:
    verdict: Verdict
    groundedness_score: float  # 0..1
    total_claims: int = 0
    supported_claims: int = 0
    unsupported_claims: list[str] = field(default_factory=list)
    skip_reason: str = ""


SYSTEM_PROMPT = (
    "You are a strict fact-checking system. You will be given an answer plus "
    "the context that was supposed to back it (numbered passages, a list of "
    "knowledge-graph facts, and possibly numbered web results). Decompose "
    "the answer into atomic factual claims and label each one.\n\n"
    "How to decompose:\n"
    "- Each claim is a single declarative sentence with subject, verb, object.\n"
    "- Split conjoined claims: 'X did A and B' → two claims.\n"
    "- Include implicit claims: 'his work on X' implies 'he worked on X'.\n"
    "- Ignore meta-statements ('The document mentions…', 'Based on…').\n\n"
    "How to label (bias UNSUPPORTED over UNCERTAIN when in doubt):\n"
    "- supported: the context contains a verbatim or near-verbatim statement "
    "of the claim. You MUST be able to copy a short phrase from the context "
    "that literally states it — if you cannot copy such a phrase, the claim "
    "is NOT supported.\n"
    "- uncertain: the context is topically related but does not directly "
    "state the claim; the claim is a plausible reading but not literal.\n"
    "- unsupported: the context contradicts the claim, is silent about it, "
    "OR uses different terminology for the same thing.\n\n"
    "Failure modes you MUST catch (real bugs from prior chats):\n"
    "1. Terminology drift. If the claim says 'workshop' but the context says "
    "'conference' (or 'Presentations & Talks', or 'seminar'), the claim is "
    "unsupported — the answer coined a different label.\n"
    "2. Attribution drift. If the claim says 'presented at X' but the context "
    "says the person 'reviewed for X' or 'was invited to X' or just lists X "
    "without an action, the claim is unsupported — different action.\n"
    "3. Quantity or date drift. Any year, count, version, or percentage in "
    "the claim must appear identically in the context. Off-by-one, "
    "rounded, or paraphrased numbers are unsupported.\n"
    "4. Entity existence. Every named entity in the claim (person, venue, "
    "paper title, organisation) must appear by name in the context. A "
    "plausible-sounding but absent entity is unsupported.\n\n"
    "Evidence field: for supported and uncertain claims, put a short "
    "VERBATIM QUOTE from the context (10-25 words) plus the citation ref "
    "in the form '\"…quote…\" [N]' or '\"…quote…\" [W#]'. For graph facts, "
    "use the entity name. For unsupported claims, leave evidence empty. "
    "Do not paraphrase — the quote is how you prove the claim is entailed.\n\n"
    "Output JSON ONLY (no markdown fences, no commentary).\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "claims": [\n'
    "    {\n"
    '      "text": "<atomic claim from the answer, quoted verbatim>",\n'
    '      "support": "supported|unsupported|uncertain",\n'
    '      "evidence": "<\\"verbatim quote\\" [N] or empty>"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    'If the answer has no factual claims, return {"claims": []}.'
)


MAX_ANSWER_CHARS = 4_000
MAX_CONTEXT_CHARS = 8_000


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _render_chunks(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no passages retrieved)"
    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        parts.append(f"[{i}] {c.text.strip()}")
    joined = "\n\n".join(parts)
    return _truncate(joined, MAX_CONTEXT_CHARS)


def _render_web(results: list[WebResult]) -> str:
    if not results:
        return "(no web results)"
    parts: list[str] = []
    for i, r in enumerate(results, start=1):
        parts.append(f"[W{i}] {r.title} — {r.url}: {r.content.strip()}")
    joined = "\n\n".join(parts)
    return _truncate(joined, MAX_CONTEXT_CHARS // 2)


def _render_facts(facts: list[GraphFact]) -> str:
    if not facts:
        return "(no graph facts)"
    lines: list[str] = []
    for f in facts:
        head = f"- {f.name} ({f.type})"
        if f.description:
            head += f": {f.description.strip()}"
        lines.append(head)
        for rel in f.relations[:6]:
            chain = " → ".join(rel.relation_chain) if rel.relation_chain else rel.relation
            lines.append(f"    → {chain} {rel.other}")
    joined = "\n".join(lines)
    return _truncate(joined, MAX_CONTEXT_CHARS // 2)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: str) -> str | None:
    if not raw:
        return None
    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return None


def _parse_claims(raw: str) -> list[ClaimVerdict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is None:
            log.warning("verification returned non-JSON: %r", raw[:200])
            return []
        try:
            data = json.loads(recovered)
        except json.JSONDecodeError:
            return []

    items = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []

    out: list[ClaimVerdict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        support = str(item.get("support") or "").strip().lower()
        if not text or support not in ("supported", "unsupported", "uncertain"):
            continue
        out.append(
            ClaimVerdict(
                text=text,
                support=support,
                evidence=str(item.get("evidence") or "").strip(),
            )
        )
    return out


def _score(claims: list[ClaimVerdict]) -> tuple[float, int, list[str]]:
    # supported=1.0, uncertain=0.5, unsupported=0.0; score is the mean.
    if not claims:
        return 1.0, 0, []
    total = 0.0
    supported = 0
    unsupported_texts: list[str] = []
    for c in claims:
        if c.support == "supported":
            total += 1.0
            supported += 1
        elif c.support == "uncertain":
            total += 0.5
        else:
            unsupported_texts.append(c.text)
    return total / len(claims), supported, unsupported_texts


def _verdict_for(score: float, *, has_claims: bool) -> Verdict:
    # An answer with no factual claims is vacuously verified.
    if not has_claims:
        return "verified"
    if score >= settings.verification_threshold_verified:
        return "verified"
    if score >= settings.verification_threshold_partial:
        return "partial"
    return "unsupported"


def _skip(reason: str) -> VerificationResult:
    return VerificationResult(verdict="skipped", groundedness_score=0.0, skip_reason=reason)


async def _call_llm(
    answer: str,
    chunks: list[RetrievedChunk],
    facts: list[GraphFact],
    web_results: list[WebResult],
) -> str:
    user_msg = (
        f"Answer to verify:\n{_truncate(answer, MAX_ANSWER_CHARS)}\n\n"
        f"Context passages:\n{_render_chunks(chunks)}\n\n"
        f"Knowledge-graph facts:\n{_render_facts(facts)}\n\n"
        f"Web results:\n{_render_web(web_results)}"
    )
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )


async def verify_answer(
    *,
    answer: str,
    chunks: list[RetrievedChunk],
    graph_facts: list[GraphFact],
    web_results: list[WebResult] | None = None,
) -> VerificationResult:
    web_results = web_results or []
    if not settings.verification_enabled:
        return _skip("verification disabled")
    if not answer or not answer.strip():
        return _skip("empty answer")
    if not chunks and not graph_facts and not web_results:
        return _skip("no context to verify against")

    try:
        raw = await _call_llm(answer, chunks, graph_facts, web_results)
    except GroqChatError as exc:
        log.warning("verification upstream failure (%s): %s", exc.status_code, exc.body)
        return _skip(f"upstream {exc.status_code}")
    except Exception as exc:  # noqa: BLE001
        log.warning("verification unexpected failure: %s", exc)
        return _skip("unexpected error")

    claims = _parse_claims(raw)
    score, supported, unsupported_texts = _score(claims)
    verdict: Verdict = _verdict_for(score, has_claims=bool(claims))

    return VerificationResult(
        verdict=verdict,
        groundedness_score=score,
        total_claims=len(claims),
        supported_claims=supported,
        unsupported_claims=unsupported_texts,
    )


def strict_refusal_for(
    result: VerificationResult,
    *,
    rag_mode: str,
    use_rag: bool,
) -> str | None:
    """Return the strict-mode refusal message when the gate should fire.

    Fails open on `skipped` verdicts — a verification outage (or
    verification_enabled=False) must not turn every strict-mode answer
    into a refusal. Boundary: score == threshold passes.
    """
    if not use_rag or rag_mode != "strict":
        return None
    if result.verdict == "skipped":
        return None
    if result.groundedness_score < settings.strict_groundedness_threshold:
        return STRICT_REFUSAL_MESSAGE
    return None


def to_dict(result: VerificationResult) -> dict[str, Any]:
    return {
        "verdict": result.verdict,
        "groundedness_score": round(result.groundedness_score, 3),
        "total_claims": result.total_claims,
        "supported_claims": result.supported_claims,
        "unsupported_claims": list(result.unsupported_claims),
        "skip_reason": result.skip_reason,
    }
