"""Classify the user's query into a workflow branch.

Intents:
  chat           — answer a factual question using retrieved chunks + graph.
  summarize      — synthesize an overview from stored document summaries.
  explain_graph  — answer using knowledge-graph relationships as the primary
                   source (skip vector retrieval).

Falls back to "chat" on any LLM failure so the workflow always has a path.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from app.core.config import settings
from app.rag.groq_chat import GroqChatError, chat_completion

log = logging.getLogger("mmap.agents.router")

Intent = Literal["chat", "summarize", "explain_graph"]
DEFAULT_INTENT: Intent = "chat"

SYSTEM_PROMPT = (
    "You route user questions in a multimodal RAG system. Classify the query "
    "into exactly one intent and return JSON only.\n\n"
    "Intents:\n"
    "- chat           — a factual question that should be answered by reading "
    "passages from the user's uploaded documents.\n"
    "- summarize      — the user wants an overview, recap, or TL;DR of one or "
    "more of their documents.\n"
    "- explain_graph  — the user is asking about entities or how things relate "
    "to each other (relationships, connections, what's linked to what).\n\n"
    "STRICT JSON schema:\n"
    '{"intent": "chat" | "summarize" | "explain_graph"}\n\n'
    "Rules:\n"
    "- Output JSON only (no markdown fences, no commentary).\n"
    '- If you are unsure, default to "chat".'
)


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


def _parse_intent(raw: str) -> Intent:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is None:
            return DEFAULT_INTENT
        try:
            data = json.loads(recovered)
        except json.JSONDecodeError:
            return DEFAULT_INTENT

    if not isinstance(data, dict):
        return DEFAULT_INTENT

    intent = data.get("intent")
    if intent in ("chat", "summarize", "explain_graph"):
        return intent  # type: ignore[return-value]
    return DEFAULT_INTENT


async def _call_llm(query: str) -> str:
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        max_tokens=64,
        response_format={"type": "json_object"},
    )


async def classify_intent(query: str) -> Intent:
    # When disabled or on any failure, take the safe "chat" path.
    if not settings.router_enabled:
        return DEFAULT_INTENT
    if not query or not query.strip():
        return DEFAULT_INTENT

    try:
        raw = await _call_llm(query.strip())
    except GroqChatError as exc:
        log.warning("intent classification upstream failure (%s): %s", exc.status_code, exc.body)
        return DEFAULT_INTENT
    except Exception as exc:  # noqa: BLE001
        log.warning("intent classification unexpected failure: %s", exc)
        return DEFAULT_INTENT

    return _parse_intent(raw)
