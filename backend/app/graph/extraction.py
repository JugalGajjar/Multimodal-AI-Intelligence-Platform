"""LLM-driven entity & relationship extraction (Groq JSON mode)."""

from __future__ import annotations

import json
import logging

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


async def extract_entities(text: str) -> ExtractionResult:
    """Call Groq with JSON mode and return a normalized ExtractionResult.

    Raises `GroqChatError` on upstream issues. Always returns a normalized
    result on success (cleaned entity names, dropped dangling rels).
    """
    if not text or not text.strip():
        return ExtractionResult(entities=[], relationships=[])

    truncated = text[:MAX_INPUT_CHARS]

    raw = await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": truncated},
        ],
        model=settings.groq_reasoning_model,
        temperature=0.0,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("entity extraction returned non-JSON: %r", raw[:200])
        return ExtractionResult(entities=[], relationships=[])

    try:
        result = ExtractionResult.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction validation failed (%s); data=%r", exc, data)
        return ExtractionResult(entities=[], relationships=[])

    return result.normalize()


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
