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
        outcome = await extraction.safe_extract_entities("anything")

    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is True


async def test_safe_extract_swallows_unexpected_errors():
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        outcome = await extraction.safe_extract_entities("anything")

    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is True


async def test_safe_extract_genuine_empty_is_not_transient(monkeypatch):
    """When the model returns a well-formed empty extraction, the outcome
    should NOT be flagged as transient — retrying would just spam Groq."""
    monkeypatch.setattr(
        "app.graph.extraction.chat_completion",
        AsyncMock(return_value='{"entities": [], "relationships": []}'),
    )
    outcome = await extraction.safe_extract_entities("hello world")
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is False


async def test_truncates_long_input(monkeypatch):
    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    long_text = "x" * 50_000
    await extraction.extract_entities(long_text)

    user_msg = fake.call_args.kwargs["messages"][1]["content"]
    assert len(user_msg) <= extraction.MAX_INPUT_CHARS


async def test_retry_on_per_minute_429_then_succeeds(monkeypatch):
    """A short-wait 429 (per-minute cap) should sleep then retry, then return."""
    payload = '{"entities": [], "relationships": []}'
    side = [
        GroqChatError(
            429,
            {"error": {"message": "Rate limit reached. Please try again in 4.8s."}},
        ),
        payload,
    ]

    async def fake_call(text):
        nxt = side.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("app.graph.extraction._call_llm", fake_call)
    monkeypatch.setattr("app.graph.extraction.asyncio.sleep", fake_sleep)

    result = await extraction.extract_entities("anything")
    assert result == ExtractionResult()
    assert len(slept) == 1
    # We sleep slightly longer than Groq's hint so the cap has actually rolled.
    assert 4.5 < slept[0] < 6.5


async def test_does_not_retry_on_per_day_429(monkeypatch):
    """A long-wait 429 (daily cap, > 30 s) should raise instead of sleeping."""
    err = GroqChatError(
        429,
        {"error": {"message": "Rate limit reached. Please try again in 14m20.112s."}},
    )
    fake = AsyncMock(side_effect=err)
    monkeypatch.setattr("app.graph.extraction._call_llm", fake)

    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("app.graph.extraction.asyncio.sleep", fake_sleep)

    with pytest.raises(GroqChatError) as exc:
        await extraction.extract_entities("anything")

    assert exc.value.status_code == 429
    assert slept == []  # never slept — bailed fast
    assert fake.await_count == 1


async def test_retries_once_on_json_validate_400(monkeypatch):
    err = GroqChatError(
        400, {"error": {"code": "json_validate_failed", "message": "Failed to validate JSON"}}
    )
    side = [err, '{"entities": [], "relationships": []}']

    async def fake_call(text):
        nxt = side.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr("app.graph.extraction._call_llm", fake_call)

    result = await extraction.extract_entities("anything")
    assert result == ExtractionResult()
    assert side == []  # both calls consumed


async def test_does_not_retry_a_second_400(monkeypatch):
    """Two 400s in a row should bail — one retry only."""
    err = GroqChatError(400, {"error": {"message": "Failed to validate JSON"}})
    fake = AsyncMock(side_effect=err)
    monkeypatch.setattr("app.graph.extraction._call_llm", fake)

    with pytest.raises(GroqChatError):
        await extraction.extract_entities("anything")

    assert fake.await_count == 2


async def test_caps_total_retries_on_repeated_per_minute_429(monkeypatch):
    err = GroqChatError(429, {"error": {"message": "Rate limit reached. Please try again in 2s."}})
    fake = AsyncMock(side_effect=err)
    monkeypatch.setattr("app.graph.extraction._call_llm", fake)

    async def fake_sleep(s):
        return None

    monkeypatch.setattr("app.graph.extraction.asyncio.sleep", fake_sleep)

    with pytest.raises(GroqChatError):
        await extraction.extract_entities("anything")

    # MAX_RETRIES is 3 — we should see exactly 3 LLM calls before bailing.
    assert fake.await_count == extraction.MAX_RETRIES


async def test_safe_extract_returns_empty_after_retries_exhausted(monkeypatch):
    err = GroqChatError(429, {"error": {"message": "Rate limit reached. Please try again in 2s."}})
    monkeypatch.setattr("app.graph.extraction._call_llm", AsyncMock(side_effect=err))

    async def fake_sleep(s):
        return None

    monkeypatch.setattr("app.graph.extraction.asyncio.sleep", fake_sleep)

    outcome = await extraction.safe_extract_entities("anything")
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is True


async def test_uses_extraction_model_not_reasoning_model(monkeypatch):
    """Entity extraction must call the configured extraction model, not the
    chat-reasoning model — they may be different (json reliability)."""
    from types import SimpleNamespace

    stub = SimpleNamespace(
        groq_extraction_model="vendor/extraction-x",
        groq_reasoning_model="vendor/chat-y",
    )
    monkeypatch.setattr("app.graph.extraction.settings", stub)

    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    await extraction.extract_entities("anything")

    assert fake.call_args.kwargs["model"] == "vendor/extraction-x"


def test_extract_json_object_handles_markdown_fence():
    raw = '```json\n{"entities": [], "relationships": []}\n```'
    assert extraction._extract_json_object(raw) == '{"entities": [], "relationships": []}'


def test_extract_json_object_handles_preamble_text():
    raw = 'Sure! Here is the JSON:\n\n{"entities": [{"name": "Qdrant"}], "relationships": []}\n'
    out = extraction._extract_json_object(raw)
    assert out is not None
    assert json.loads(out) == {"entities": [{"name": "Qdrant"}], "relationships": []}


def test_extract_json_object_respects_nesting():
    raw = 'noise {"a": {"b": "}"}, "c": 1} trailing prose'
    out = extraction._extract_json_object(raw)
    assert out is not None
    assert json.loads(out) == {"a": {"b": "}"}, "c": 1}


def test_extract_json_object_returns_none_on_no_object():
    assert extraction._extract_json_object("no json here at all") is None
    assert extraction._extract_json_object("") is None


async def test_parser_recovers_from_preamble_and_fences(monkeypatch):
    """A model wrapping its JSON in chatter or markdown should still parse."""
    raw = 'Here you go:\n```json\n{"entities": [{"name": "Bandit", "type": "Technology", "description": "linter"}], "relationships": []}\n```'
    monkeypatch.setattr("app.graph.extraction._call_llm", AsyncMock(return_value=raw))

    result = await extraction.extract_entities("anything")
    assert len(result.entities) == 1
    assert result.entities[0].name == "Bandit"


def test_parse_retry_after_handles_known_groq_formats():
    p = extraction._parse_retry_after
    assert p({"error": {"message": "try again in 4.8s"}}) == pytest.approx(4.8)
    assert p({"error": {"message": "try again in 17.3325s"}}) == pytest.approx(17.3325)
    assert p({"error": {"message": "try again in 14m20.112s"}}) == pytest.approx(860.112)
    assert p({"error": {"message": "no hint here"}}) is None
    assert p({}) is None
    assert p("opaque string") is None


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
