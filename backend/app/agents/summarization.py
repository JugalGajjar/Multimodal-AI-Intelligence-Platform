"""Produce a structured TL;DR + key points + topics for a document.

On any LLM failure (rate limit, JSON parse), returns an empty SummaryResult
so the ingest pipeline never fails because of summarization.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.core.config import settings
from app.rag.groq_chat import GroqChatError, chat_completion

log = logging.getLogger("mmap.agents.summarization")


@dataclass(frozen=True)
class SummaryResult:
    tldr: str = ""
    key_points: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.tldr and not self.key_points and not self.topics


SYSTEM_PROMPT = (
    "You are a careful summarization system. Read the document text and produce "
    "a structured summary that a busy user can skim in under 10 seconds.\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "tldr": "<one or two sentences>",\n'
    '  "key_points": ["<bullet 1>", "<bullet 2>", ...],  // 3 to 6 items\n'
    '  "topics": ["<short label>", ...]                  // 3 to 6 items\n'
    "}\n\n"
    "Rules:\n"
    "- TLDR must be a single declarative paragraph (≤ 2 sentences).\n"
    "- Each key point is a complete short sentence (≤ 25 words).\n"
    "- Topics are 1–3 word labels (e.g. 'authentication', 'vector search').\n"
    "- Use facts from the document only; do not invent or speculate.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    '- If the text is empty or unintelligible, return {"tldr": "", "key_points": [], "topics": []}.'
)


MAX_INPUT_CHARS = 14_000
MAX_TLDR_CHARS = 600
MAX_KEY_POINTS = 8
MAX_TOPICS = 8
MAX_POINT_CHARS = 280
MAX_TOPIC_CHARS = 80


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


def _clean_list(items: object, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rstrip() + "…"
        out.append(cleaned)
        if len(out) >= max_items:
            break

    seen: set[str] = set()
    deduped: list[str] = []
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _parse_response(raw: str) -> SummaryResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is None:
            log.warning("summarization returned non-JSON: %r", raw[:200])
            return SummaryResult()
        try:
            data = json.loads(recovered)
        except json.JSONDecodeError:
            return SummaryResult()

    if not isinstance(data, dict):
        return SummaryResult()

    tldr_raw = data.get("tldr")
    tldr = tldr_raw.strip() if isinstance(tldr_raw, str) else ""
    if len(tldr) > MAX_TLDR_CHARS:
        tldr = tldr[:MAX_TLDR_CHARS].rstrip() + "…"

    key_points = _clean_list(
        data.get("key_points"),
        max_items=MAX_KEY_POINTS,
        max_chars=MAX_POINT_CHARS,
    )
    topics = _clean_list(
        data.get("topics"),
        max_items=MAX_TOPICS,
        max_chars=MAX_TOPIC_CHARS,
    )

    return SummaryResult(tldr=tldr, key_points=key_points, topics=topics)


async def _call_llm(text: str) -> str:
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )


async def summarize_document(text: str) -> SummaryResult:
    # Empty result on any failure — worker treats it as "no summary stored".
    if not text or not text.strip():
        return SummaryResult()

    truncated = text[:MAX_INPUT_CHARS]

    try:
        raw = await _call_llm(truncated)
    except GroqChatError as exc:
        log.warning("summarization upstream failure (%s): %s", exc.status_code, exc.body)
        return SummaryResult()
    except Exception as exc:  # noqa: BLE001
        log.warning("summarization unexpected failure: %s", exc)
        return SummaryResult()

    return _parse_response(raw)
