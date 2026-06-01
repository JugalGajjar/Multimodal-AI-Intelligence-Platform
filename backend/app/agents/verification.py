"""Verification agent (Phase 5.2).

Re-reads an answer against the context (cited chunks + knowledge-graph facts)
and emits a structured groundedness verdict:

    verified    — every atomic claim is supported by the context
    partial     — some claims are unsupported (above the partial threshold)
    unsupported — most claims are unsupported (below the partial threshold)
    skipped     — verification didn't run (no context, disabled, or LLM error)

The model is asked to:

  1. Decompose the answer into atomic factual claims.
  2. Label each as `supported | unsupported | uncertain` against the context.
  3. Quote which passage / graph fact backs the supported ones.

`uncertain` counts as half-support so a hedged answer doesn't get penalised
as harshly as an outright fabrication.
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
from app.rag.retrieval import RetrievedChunk

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
    "the context that was supposed to back it (numbered passages and a list "
    "of knowledge-graph facts). Decompose the answer into atomic factual "
    "claims and label each one.\n\n"
    "Rules:\n"
    "- Each claim must be a single declarative sentence.\n"
    "- Ignore meta-statements ('I will explain…', 'The document mentions…').\n"
    '- Support = "supported" only if the context literally entails it.\n'
    '- "uncertain" when the context partially implies it but does not state it.\n'
    '- "unsupported" when the context contradicts it OR is silent about it.\n'
    "- Output JSON ONLY (no markdown fences, no commentary).\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "claims": [\n'
    '    {"text": "<atomic claim>", "support": "supported|unsupported|uncertain", '
    '"evidence": "<[N] citation marker or graph entity name, empty if unsupported>"}\n'
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
    """Return (groundedness_score, supported_count, unsupported_texts).

    Scoring:
      supported   = 1.0
      uncertain   = 0.5
      unsupported = 0.0
    Score is the mean across all claims.
    """
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
    if not has_claims:
        # Vacuously verified — no factual claims to check.
        return "verified"
    if score >= settings.verification_threshold_verified:
        return "verified"
    if score >= settings.verification_threshold_partial:
        return "partial"
    return "unsupported"


def _skip(reason: str) -> VerificationResult:
    return VerificationResult(verdict="skipped", groundedness_score=0.0, skip_reason=reason)


async def _call_llm(answer: str, chunks: list[RetrievedChunk], facts: list[GraphFact]) -> str:
    user_msg = (
        f"Answer to verify:\n{_truncate(answer, MAX_ANSWER_CHARS)}\n\n"
        f"Context passages:\n{_render_chunks(chunks)}\n\n"
        f"Knowledge-graph facts:\n{_render_facts(facts)}"
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
) -> VerificationResult:
    """Verify `answer` against the cited context.

    Returns a `VerificationResult` with the verdict, groundedness score, and
    the list of unsupported claim texts (for UI surfacing).

    Skipped — and treated as best-effort — when:
      - the feature is disabled in settings,
      - the answer is empty / whitespace,
      - there is no context AND no graph facts to verify against,
      - the LLM call fails (rate limit, JSON parse error, etc.).
    """
    if not settings.verification_enabled:
        return _skip("verification disabled")
    if not answer or not answer.strip():
        return _skip("empty answer")
    if not chunks and not graph_facts:
        return _skip("no context to verify against")

    try:
        raw = await _call_llm(answer, chunks, graph_facts)
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


def to_dict(result: VerificationResult) -> dict[str, Any]:
    """Serializer used by the workflow → router → ChatResponse plumbing."""
    return {
        "verdict": result.verdict,
        "groundedness_score": round(result.groundedness_score, 3),
        "total_claims": result.total_claims,
        "supported_claims": result.supported_claims,
        "unsupported_claims": list(result.unsupported_claims),
        "skip_reason": result.skip_reason,
    }
