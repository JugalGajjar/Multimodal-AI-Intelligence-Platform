"""Unit tests for the LLM-driven entity extraction wrapper."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.graph import extraction
from app.graph.schema import ExtractionResult
from app.rag.groq_chat import GroqChatError


async def test_empty_text_returns_empty_without_llm_call():
    with patch("app.graph.extraction.chat_completion", new=AsyncMock()) as fake_call:
        result = await extraction.extract_entities("   ")

    assert result.entities == []
    fake_call.assert_not_called()


async def test_parses_well_formed_json_and_normalizes():
    payload = {
        "entities": [
            {"name": "Qdrant", "type": "Technology", "description": "vector db"},
            {"name": "qdrant", "type": "Technology", "description": "dup"},  # dup
        ],
        "relationships": [
            {"source": "Qdrant", "target": "Qdrant", "relation": "is itself"},  # self-loop
        ],
    }
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(return_value=json.dumps(payload)),
    ):
        result = await extraction.extract_entities("anything")

    assert len(result.entities) == 1
    assert result.relationships == []


async def test_uses_json_response_format(monkeypatch):
    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    await extraction.extract_entities("some text")

    kwargs = fake.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0


async def test_non_json_response_returns_empty():
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(return_value="hi I am not json"),
    ):
        result = await extraction.extract_entities("anything")

    assert result == ExtractionResult()


async def test_malformed_schema_returns_empty():
    bad = json.dumps({"entities": [{"foo": "bar"}]})  # missing required `name`
    with patch("app.graph.extraction.chat_completion", new=AsyncMock(return_value=bad)):
        result = await extraction.extract_entities("anything")

    assert result == ExtractionResult()


async def test_safe_extract_swallows_upstream_errors():
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate limited"})),
    ):
        result = await extraction.safe_extract_entities("anything")

    assert result == ExtractionResult()


async def test_safe_extract_swallows_unexpected_errors():
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await extraction.safe_extract_entities("anything")

    assert result == ExtractionResult()


async def test_truncates_long_input(monkeypatch):
    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    long_text = "x" * 50_000
    await extraction.extract_entities(long_text)

    user_msg = fake.call_args.kwargs["messages"][1]["content"]
    assert len(user_msg) <= extraction.MAX_INPUT_CHARS


@pytest.mark.asyncio
async def test_returns_clean_result_for_realistic_payload():
    payload = json.dumps(
        {
            "entities": [
                {
                    "name": "Qdrant",
                    "type": "Technology",
                    "description": "open-source vector database",
                },
                {
                    "name": "Cosine Distance",
                    "type": "Concept",
                    "description": "vector similarity metric",
                },
                {
                    "name": "BAAI/bge-small-en-v1.5",
                    "type": "Technology",
                    "description": "384-dim embedding model",
                },
            ],
            "relationships": [
                {
                    "source": "Qdrant",
                    "target": "Cosine Distance",
                    "relation": "uses",
                },
            ],
        }
    )
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(return_value=payload),
    ):
        result = await extraction.extract_entities("some text")

    assert len(result.entities) == 3
    assert len(result.relationships) == 1
    assert {e.name for e in result.entities} == {
        "Qdrant",
        "Cosine Distance",
        "BAAI/bge-small-en-v1.5",
    }
