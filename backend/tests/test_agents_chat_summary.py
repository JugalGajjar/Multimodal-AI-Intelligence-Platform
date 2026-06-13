"""Unit tests for the chat title/summary agent. Groq is mocked."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import chat_summary as cs
from app.agents.chat_summary import ChatSummaryResult, summarize_chat
from app.rag.groq_chat import GroqChatError

TURNS = [
    {"role": "user", "content": "What is prompt engineering?"},
    {"role": "assistant", "content": "Designing clear instructions for AI models."},
]


async def test_happy_path_parses_title_and_summary():
    raw = json.dumps({"title": "Prompt engineering basics", "summary": "User asked about it."})
    with patch.object(cs, "chat_completion", new=AsyncMock(return_value=raw)) as fake:
        result = await summarize_chat(TURNS)

    assert result == ChatSummaryResult(
        title="Prompt engineering basics", summary="User asked about it."
    )
    kwargs = fake.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "user: What is prompt engineering?" in kwargs["messages"][1]["content"]


async def test_recovers_from_fenced_json():
    raw = '```json\n{"title": "T", "summary": "S"}\n```'
    with patch.object(cs, "chat_completion", new=AsyncMock(return_value=raw)):
        result = await summarize_chat(TURNS)
    assert result.title == "T"
    assert result.summary == "S"


async def test_clamps_title_to_60_chars():
    raw = json.dumps({"title": "x" * 200, "summary": "ok"})
    with patch.object(cs, "chat_completion", new=AsyncMock(return_value=raw)):
        result = await summarize_chat(TURNS)
    assert len(result.title) == 60
    assert result.title.endswith("…")


async def test_empty_turns_short_circuits_without_llm_call():
    with patch.object(cs, "chat_completion", new=AsyncMock()) as fake:
        result = await summarize_chat([])
    assert result.is_empty()
    fake.assert_not_awaited()


async def test_groq_failure_returns_empty_result():
    with patch.object(
        cs,
        "chat_completion",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate"})),
    ):
        result = await summarize_chat(TURNS)
    assert result.is_empty()


async def test_garbage_response_returns_empty_result():
    with patch.object(cs, "chat_completion", new=AsyncMock(return_value="not json at all")):
        result = await summarize_chat(TURNS)
    assert result.is_empty()


def test_transcript_drops_oldest_when_over_budget():
    turns = [{"role": "user", "content": f"msg-{i} " + "y" * 490} for i in range(12)]
    transcript = cs._build_transcript(turns)
    assert len(transcript) <= cs.MAX_TRANSCRIPT_CHARS
    assert "msg-11" in transcript  # newest kept
    assert "msg-0 " not in transcript  # oldest dropped


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_transcript_skips_blank_messages(bad):
    transcript = cs._build_transcript([{"role": "user", "content": bad}])
    assert transcript == ""
