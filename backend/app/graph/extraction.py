"""LLM-driven entity & relationship extraction (Groq JSON mode).

Retry behavior:
  - 429 with a per-minute / per-second hint (`try again in <=30s`): sleep and
    retry, up to MAX_RETRIES total attempts.
  - 429 with a long hint (per-day cap): bail immediately — the caller can use
    the reindex endpoint once the cap resets.
  - 400 `json_validate_failed`: retry once. The model is non-deterministic and
    a second attempt at the same input often succeeds.
  - Anything else: bail (caller falls back to an empty result).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from app.core.config import settings
from app.graph.schema import ExtractionResult
from app.rag.groq_chat import GroqChatError, chat_completion

log = logging.getLogger("mmap.graph.extraction")

SYSTEM_PROMPT = (
    "You are an information extraction system. Read the passage and produce a "
    "JSON object describing the entities mentioned and how they relate.\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "entities": [\n'
    '    {"name": "<canonical noun phrase>", "type": "Person|Organization|'
    'Location|Concept|Technology|Product|Event|Date", '
    '"description": "<one short sentence>"}\n'
    "  ],\n"
    '  "relationships": [\n'
    '    {"source": "<entity name>", "target": "<entity name>", '
    '"relation": "<verb phrase, e.g. \\"uses\\", \\"located in\\">"}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    '- Names must be canonical (no pronouns, drop articles like "the").\n'
    "- Each relationship source/target MUST appear in entities.\n"
    "- If unsure of entity type, use Concept.\n"
    "- Prefer named, specific entities; skip generic words.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    '- Return {"entities": [], "relationships": []} if nothing notable.'
)


MAX_INPUT_CHARS = 12_000
MAX_RETRIES = 3
RETRY_BACKOFF_CAP_SECONDS = 30.0
# Anything longer than this in the "try again in X" hint is treated as a
# daily-cap that's not worth blocking on inside a worker job.
RETRY_GIVE_UP_SECONDS = 30.0


_RETRY_AFTER_PATTERNS = (
    # Groq messages: "Please try again in 4.8s" / "in 17.3325s" / "in 14m20.112s"
    re.compile(r"try again in (\d+)m([\d.]+)s", re.IGNORECASE),
    re.compile(r"try again in ([\d.]+)s", re.IGNORECASE),
    re.compile(r"try again in ([\d.]+)ms", re.IGNORECASE),
)


def _parse_retry_after(body: object) -> float | None:
    """Extract Groq's wait hint (in seconds) from an error body. None if absent."""
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
    """Best-effort string extraction from Groq's error body."""
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
        max_tokens=2048,
        response_format={"type": "json_object"},
    )


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: str) -> str | None:
    """Lift the first JSON object out of `raw`, tolerating markdown fences and
    a leading sentence of preamble. Returns None if no object-shaped substring
    can be found."""
    if not raw:
        return None

    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        return fenced.group(1)

    # Walk from the first '{' to its matching '}', counting nesting and
    # respecting string literals so a `"}"` inside a value doesn't fool us.
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
        # The model emitted preamble / fences / trailing prose around its JSON.
        # Try to recover by locating the first JSON object substring.
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
    """Call Groq with JSON mode and return a normalized ExtractionResult.

    Raises `GroqChatError` on upstream issues that can't be recovered from
    via retry (e.g. daily-cap 429, missing key, server error). Returns an
    empty `ExtractionResult` when the model returns garbage we can't parse.
    """
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


async def safe_extract_entities(text: str) -> ExtractionResult:
    """Same as extract_entities but maps upstream failures to an empty result
    so the surrounding worker pipeline never aborts because of extraction."""
    try:
        return await extract_entities(text)
    except GroqChatError as exc:
        log.warning("extraction upstream failure (%s): %s", exc.status_code, exc.body)
        return ExtractionResult(entities=[], relationships=[])
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction unexpected failure: %s", exc)
        return ExtractionResult(entities=[], relationships=[])
