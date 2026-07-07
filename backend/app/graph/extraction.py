"""LLM-driven entity & relationship extraction with backoff.

Retry rules:
  429 with hint ≤ 30s  → sleep + retry (per-minute cap), up to MAX_RETRIES.
  429 with hint > 30s  → bail (daily cap; worker shouldn't block).
  400 json_validate    → retry once (model is non-deterministic).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from app.core.config import settings
from app.graph.schema import ExtractionResult
from app.rag.groq_chat import GroqChatError, chat_completion


@dataclass(frozen=True)
class ExtractionOutcome:
    """Outcome of a `safe_extract_entities` call. `transient_failure=True`
    means the model never produced a valid result (429/400/network) and a
    retry from the caller is likely to succeed; `transient_failure=False`
    with an empty result means the model genuinely found no entities."""

    result: ExtractionResult
    transient_failure: bool


log = logging.getLogger("mmap.graph.extraction")

SYSTEM_PROMPT = (
    "You are an information extraction system. Read the passage and produce a "
    "JSON object describing the entities mentioned and how they relate. Works "
    "across any domain — medical, legal, business, scientific, technical.\n\n"
    "STRICT JSON schema (types are exactly one of the eight allowed values):\n"
    "{\n"
    '  "entities": [\n'
    '    {"name": "canonical noun phrase", "type": "Person", '
    '"description": "2-6 word tag"}\n'
    "  ],\n"
    '  "relationships": [\n'
    '    {"source": "entity name", "target": "entity name", '
    '"relation": "short verb phrase"}\n'
    "  ]\n"
    "}\n"
    "Allowed entity types: Person, Organization, Location, Concept, "
    "Technology, Product, Event, Date.\n\n"
    "Rules:\n"
    '- Names must be canonical (no pronouns, drop articles like "the").\n'
    "- Each relationship source and target MUST appear in entities.\n"
    "- If unsure of entity type, use Concept.\n"
    "- Prefer named, specific entities; skip generic words.\n"
    "- Descriptions MUST be a 2-6 word tag (role, category, or one-liner) "
    "— never a full sentence. Long descriptions waste output tokens that "
    "would otherwise go to relationships.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    "- Only return empty lists when the passage contains no named entities "
    "at all. If entities are present, you MUST extract every relation the "
    "passage implies, including relations expressed through:\n"
    '  * apposition or parentheses ("Jane Smith (MIT)" → Smith affiliated with MIT)\n'
    "  * juxtaposition on the same line/slide (title-slide bylines, author lists,\n"
    "    tables where a row groups related entities)\n"
    '  * comparison and result verbs ("outperforms", "reduces", "increases", "cites")\n'
    '  * possessive or attributive prose ("Anthropic\'s Claude", "the FDA-approved drug")\n'
    "- Slide, OCR, and bullet-list text is often compact — infer the relation "
    "from proximity when the surrounding text makes it unambiguous.\n\n"
    "Example (illustrates typing + explicit + implicit relations — the domain "
    "is illustrative, apply the same reasoning to whatever passage you receive):\n"
    'Input: "Jane Smith (MIT) proposes TinyGraph — a variant that outperforms '
    'GraphBERT on the WebQA benchmark."\n'
    "Output:\n"
    "{\n"
    '  "entities": [\n'
    '    {"name": "Jane Smith", "type": "Person", "description": "researcher"},\n'
    '    {"name": "MIT", "type": "Organization", "description": "research institution"},\n'
    '    {"name": "TinyGraph", "type": "Technology", "description": "lightweight graph model"},\n'
    '    {"name": "GraphBERT", "type": "Technology", "description": "baseline graph model"},\n'
    '    {"name": "WebQA", "type": "Concept", "description": "QA benchmark"}\n'
    "  ],\n"
    '  "relationships": [\n'
    '    {"source": "Jane Smith", "target": "MIT", "relation": "affiliated with"},\n'
    '    {"source": "Jane Smith", "target": "TinyGraph", "relation": "proposes"},\n'
    '    {"source": "TinyGraph", "target": "GraphBERT", "relation": "outperforms"},\n'
    '    {"source": "TinyGraph", "target": "WebQA", "relation": "evaluated on"}\n'
    "  ]\n"
    "}"
)


MAX_INPUT_CHARS = 12_000
MAX_RETRIES = 3
RETRY_BACKOFF_CAP_SECONDS = 30.0
# Wait hints longer than this are treated as a daily cap.
RETRY_GIVE_UP_SECONDS = 30.0


# Groq messages: "Please try again in 4.8s" / "in 17.3325s" / "in 14m20.112s"
_RETRY_AFTER_PATTERNS = (
    re.compile(r"try again in (\d+)m([\d.]+)s", re.IGNORECASE),
    re.compile(r"try again in ([\d.]+)s", re.IGNORECASE),
    re.compile(r"try again in ([\d.]+)ms", re.IGNORECASE),
)


def _parse_retry_after(body: object) -> float | None:
    msg = _error_message(body)
    if not msg:
        return None
    for pat in _RETRY_AFTER_PATTERNS:
        m = pat.search(msg)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2:
            return float(groups[0]) * 60 + float(groups[1])
        value = float(groups[0])
        if "ms" in pat.pattern:
            return value / 1000.0
        return value
    return None


def _error_message(body: object) -> str:
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        err = body.get("error") if "error" in body else None
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(body.get("detail"), str):
            return body["detail"]
    return str(body)


def _is_json_validate_failure(exc: GroqChatError) -> bool:
    if exc.status_code != 400:
        return False
    msg = _error_message(exc.body).lower()
    return "validate json" in msg or "json_validate_failed" in msg


async def _call_llm(text: str) -> str:
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        # reasoning_effort="medium" — graph extraction needs proper reasoning
        # to infer relations from proximity/apposition; "low" would revert to
        # the observed "8 entities, 0 relations" behavior we saw in prod.
        # max_tokens=5120 (was 8192 in #42a) — Groq free tier caps gpt-oss
        # at 8000 TPM AND enforces the cap on individual requests. 8192 +
        # input + system prompt exceeded 8000 → 413. 5120 keeps single
        # calls under the ceiling while still fitting ~80 entities with
        # the #42a terse-description rule ("2-6 word tag"). Proper fix is
        # the planned #43 map-reduce redesign — this is the interim ceiling.
        max_tokens=5120,
        reasoning_effort="medium",
        response_format={"type": "json_object"},
    )


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: str) -> str | None:
    # Lift the first JSON object out, tolerating fences and prose preamble.
    if not raw:
        return None

    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        return fenced.group(1)

    # Walk braces while respecting string literals so a `"}"` doesn't fool us.
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


def _parse_response(raw: str) -> ExtractionResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is None:
            log.warning("entity extraction returned non-JSON: %r", raw[:200])
            return ExtractionResult(entities=[], relationships=[])
        try:
            data = json.loads(recovered)
        except json.JSONDecodeError:
            log.warning("entity extraction JSON recovery failed: %r", raw[:200])
            return ExtractionResult(entities=[], relationships=[])

    try:
        result = ExtractionResult.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction validation failed (%s); data=%r", exc, data)
        return ExtractionResult(entities=[], relationships=[])

    return result.normalize()


async def extract_entities(text: str) -> ExtractionResult:
    # Raises GroqChatError on unrecoverable upstream issues. Returns an empty
    # result when the model returns garbage we can't parse.
    if not text or not text.strip():
        return ExtractionResult(entities=[], relationships=[])

    truncated = text[:MAX_INPUT_CHARS]
    json_retry_used = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = await _call_llm(truncated)
            return _parse_response(raw)
        except GroqChatError as exc:
            if exc.status_code == 429:
                wait = _parse_retry_after(exc.body)
                if wait is not None and wait <= RETRY_GIVE_UP_SECONDS and attempt < MAX_RETRIES:
                    sleep_for = min(wait + 0.5, RETRY_BACKOFF_CAP_SECONDS)
                    log.info(
                        "extraction 429: per-minute cap, sleeping %.1fs (attempt %d/%d)",
                        sleep_for,
                        attempt,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(sleep_for)
                    continue
                # Daily cap (or we've exhausted retries) — surface up.
                raise
            if _is_json_validate_failure(exc) and not json_retry_used:
                json_retry_used = True
                log.info("extraction 400 json_validate_failed — retrying once")
                continue
            raise

    # Loop exit without return means we exhausted retries on 429s.
    raise GroqChatError(429, {"detail": f"extraction exhausted {MAX_RETRIES} retries"})


async def safe_extract_entities(text: str) -> ExtractionOutcome:
    """Wraps `extract_entities` and never raises. Returns an outcome that
    also tells the caller whether the empty case was due to a transient
    upstream issue (retry likely to succeed) or a real empty extraction."""
    try:
        return ExtractionOutcome(
            result=await extract_entities(text),
            transient_failure=False,
        )
    except GroqChatError as exc:
        log.warning("extraction upstream failure (%s): %s", exc.status_code, exc.body)
        return ExtractionOutcome(
            result=ExtractionResult(entities=[], relationships=[]),
            transient_failure=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction unexpected failure: %s", exc)
        return ExtractionOutcome(
            result=ExtractionResult(entities=[], relationships=[]),
            transient_failure=True,
        )
