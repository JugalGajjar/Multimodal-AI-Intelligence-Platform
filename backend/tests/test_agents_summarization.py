"""Unit tests for the summarization agent."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import summarization as summ
from app.agents.summarization import SummaryResult, summarize_document
from app.rag.groq_chat import GroqChatError


class TestParseResponse:
    def test_well_formed_response_parses(self):
        raw = json.dumps(
            {
                "tldr": "The platform does X.",
                "key_points": ["A", "B", "C"],
                "topics": ["x", "y"],
            }
        )
        out = summ._parse_response(raw)
        assert out.tldr == "The platform does X."
        assert out.key_points == ["A", "B", "C"]
        assert out.topics == ["x", "y"]

    def test_dedupes_key_points_case_insensitively(self):
        raw = json.dumps({"tldr": "x", "key_points": ["AA", "aa", "BB"], "topics": []})
        out = summ._parse_response(raw)
        assert out.key_points == ["AA", "BB"]

    def test_truncates_overlong_tldr(self):
        long = "x" * (summ.MAX_TLDR_CHARS + 100)
        raw = json.dumps({"tldr": long, "key_points": [], "topics": []})
        out = summ._parse_response(raw)
        assert len(out.tldr) <= summ.MAX_TLDR_CHARS + 1  # +1 for ellipsis
        assert out.tldr.endswith("…")

    def test_truncates_overlong_key_point(self):
        long = "y" * (summ.MAX_POINT_CHARS + 100)
        raw = json.dumps({"tldr": "x", "key_points": [long], "topics": []})
        out = summ._parse_response(raw)
        assert out.key_points[0].endswith("…")
        assert len(out.key_points[0]) <= summ.MAX_POINT_CHARS + 1

    def test_caps_key_points_count(self):
        raw = json.dumps({"tldr": "x", "key_points": [f"pt-{i}" for i in range(20)], "topics": []})
        out = summ._parse_response(raw)
        assert len(out.key_points) == summ.MAX_KEY_POINTS

    def test_caps_topics_count(self):
        raw = json.dumps(
            {"tldr": "x", "key_points": [], "topics": [f"topic{i}" for i in range(20)]}
        )
        out = summ._parse_response(raw)
        assert len(out.topics) == summ.MAX_TOPICS

    def test_drops_non_string_items(self):
        raw = json.dumps({"tldr": "x", "key_points": ["good", 42, None, "also good"], "topics": []})
        out = summ._parse_response(raw)
        assert out.key_points == ["good", "also good"]

    def test_recovers_from_markdown_fenced_json(self):
        raw = '```json\n{"tldr":"x","key_points":["a"],"topics":["t"]}\n```'
        out = summ._parse_response(raw)
        assert out.tldr == "x"
        assert out.key_points == ["a"]

    def test_recovers_from_preamble_text(self):
        raw = 'Sure! Here:\n{"tldr":"x","key_points":["a"],"topics":[]}'
        out = summ._parse_response(raw)
        assert out.tldr == "x"

    def test_non_json_returns_empty(self):
        assert summ._parse_response("definitely not json") == SummaryResult()

    def test_non_dict_payload_returns_empty(self):
        assert summ._parse_response('["a", "b"]') == SummaryResult()

    def test_missing_fields_returns_partial(self):
        raw = json.dumps({"tldr": "only tldr"})
        out = summ._parse_response(raw)
        assert out.tldr == "only tldr"
        assert out.key_points == []
        assert out.topics == []


@pytest.mark.asyncio
async def test_summarize_empty_text_returns_empty_without_llm_call():
    with patch.object(summ, "_call_llm", new=AsyncMock()) as fake_call:
        result = await summarize_document("   ")

    assert result == SummaryResult()
    fake_call.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_truncates_long_input(monkeypatch):
    fake = AsyncMock(return_value='{"tldr":"x","key_points":[],"topics":[]}')
    monkeypatch.setattr(summ, "chat_completion", fake)

    await summarize_document("a" * 50_000)

    user_msg = fake.call_args.kwargs["messages"][1]["content"]
    assert len(user_msg) <= summ.MAX_INPUT_CHARS


@pytest.mark.asyncio
async def test_summarize_returns_empty_on_rate_limit():
    with patch.object(
        summ,
        "_call_llm",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate limited"})),
    ):
        result = await summarize_document("anything")

    assert result == SummaryResult()


@pytest.mark.asyncio
async def test_summarize_returns_empty_on_unexpected_error():
    with patch.object(summ, "_call_llm", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = await summarize_document("anything")

    assert result == SummaryResult()


@pytest.mark.asyncio
async def test_summarize_uses_extraction_model_and_json_mode(monkeypatch):
    """Summarization shares the extraction model — the chat reasoning model
    isn't reliable under strict JSON mode on noisy OCR text."""
    monkeypatch.setattr(summ.settings, "groq_extraction_model", "vendor/sum-x")
    fake = AsyncMock(return_value='{"tldr":"x","key_points":[],"topics":[]}')
    monkeypatch.setattr(summ, "chat_completion", fake)

    await summarize_document("anything")

    kwargs = fake.call_args.kwargs
    assert kwargs["model"] == "vendor/sum-x"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0
    # Summarization is structured extraction — low CoT is enough. See #41.
    assert kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_summarize_realistic_payload_round_trip():
    raw = json.dumps(
        {
            "tldr": "The platform performs multimodal RAG.",
            "key_points": [
                "It uses BAAI/bge-small-en-v1.5 for embeddings.",
                "Qdrant stores 384-dimensional vectors.",
                "Audio is transcribed with Groq Whisper.",
            ],
            "topics": ["multimodal RAG", "vector search", "audio transcription"],
        }
    )
    with patch.object(summ, "_call_llm", new=AsyncMock(return_value=raw)):
        result = await summarize_document("the doc text")

    assert "multimodal RAG" in result.tldr
    assert len(result.key_points) == 3
    assert "vector search" in result.topics


def test_is_empty_returns_true_when_all_fields_blank():
    assert SummaryResult().is_empty() is True
    assert SummaryResult(tldr="x").is_empty() is False
    assert SummaryResult(key_points=["a"]).is_empty() is False
    assert SummaryResult(topics=["t"]).is_empty() is False
