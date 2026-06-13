"""Title + short summary for a chat thread. Failure returns an empty result."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.agents.summarization import _extract_json_object
from app.core.config import settings
from app.rag.groq_chat import GroqChatError, chat_completion

log = logging.getLogger("mmap.agents.chat_summary")

MAX_TURN_MESSAGES = 12  # last ~6 turns
MAX_MESSAGE_CHARS = 500
MAX_TRANSCRIPT_CHARS = 6_000
MAX_TITLE_CHARS = 60
MAX_SUMMARY_CHARS = 400

SYSTEM_PROMPT = (
    "You name and summarize a chat between a user and a document-QA "
    "assistant. Output JSON ONLY (no markdown fences, no commentary).\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "title": "<concise noun-phrase describing the topic, max 60 characters, no quotes>",\n'
    '  "summary": "<1-2 sentences describing what was asked and answered>"\n'
    "}\n"
    'If the transcript is empty return {"title": "", "summary": ""}.'
)


@dataclass(frozen=True)
class ChatSummaryResult:
    title: str = ""
    summary: str = ""

    def is_empty(self) -> bool:
        return not self.title and not self.summary


def _clamp(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _build_transcript(turns: list[dict[str, str]]) -> str:
    recent = turns[-MAX_TURN_MESSAGES:]
    lines: list[str] = []
    for t in recent:
        role = str(t.get("role") or "").strip()
        content = _clamp(str(t.get("content") or ""), MAX_MESSAGE_CHARS)
        if role and content:
            lines.append(f"{role}: {content}")
    while lines and sum(len(line) + 1 for line in lines) > MAX_TRANSCRIPT_CHARS:
        lines.pop(0)
    return "\n".join(lines)


async def summarize_chat(turns: list[dict[str, str]]) -> ChatSummaryResult:
    transcript = _build_transcript(turns)
    if not transcript:
        return ChatSummaryResult()

    try:
        raw = await chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            model=settings.groq_extraction_model,
            temperature=0.0,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
    except GroqChatError as exc:
        log.warning("chat summary upstream failure (%s): %s", exc.status_code, exc.body)
        return ChatSummaryResult()
    except Exception as exc:  # noqa: BLE001
        log.warning("chat summary unexpected failure: %s", exc)
        return ChatSummaryResult()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is None:
            log.warning("chat summary returned non-JSON: %r", raw[:200])
            return ChatSummaryResult()
        try:
            data = json.loads(recovered)
        except json.JSONDecodeError:
            return ChatSummaryResult()

    if not isinstance(data, dict):
        return ChatSummaryResult()

    return ChatSummaryResult(
        title=_clamp(str(data.get("title") or ""), MAX_TITLE_CHARS),
        summary=_clamp(str(data.get("summary") or ""), MAX_SUMMARY_CHARS),
    )
