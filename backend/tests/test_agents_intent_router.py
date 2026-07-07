"""Unit tests for the intent router."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents import intent_router as ir
from app.agents.intent_router import classify_intent
from app.rag.groq_chat import GroqChatError


class TestParseIntent:
    def test_well_formed_chat(self):
        assert ir._parse_intent('{"intent": "chat"}') == "chat"

    def test_well_formed_summarize(self):
        assert ir._parse_intent('{"intent": "summarize"}') == "summarize"

    def test_well_formed_explain_graph(self):
        assert ir._parse_intent('{"intent": "explain_graph"}') == "explain_graph"

    def test_unknown_intent_falls_back_to_chat(self):
        assert ir._parse_intent('{"intent": "make_coffee"}') == "chat"

    def test_recovers_from_markdown_fence(self):
        raw = '```json\n{"intent": "summarize"}\n```'
        assert ir._parse_intent(raw) == "summarize"

    def test_recovers_from_preamble(self):
        raw = 'Sure!\n{"intent": "explain_graph"}'
        assert ir._parse_intent(raw) == "explain_graph"

    def test_non_json_falls_back_to_chat(self):
        assert ir._parse_intent("not json at all") == "chat"

    def test_missing_intent_key_falls_back_to_chat(self):
        assert ir._parse_intent('{"other": "value"}') == "chat"

    def test_non_dict_payload_falls_back_to_chat(self):
        assert ir._parse_intent('["chat"]') == "chat"


@pytest.mark.asyncio
async def test_classify_intent_disabled_returns_default(monkeypatch):
    monkeypatch.setattr(ir.settings, "router_enabled", False)
    intent = await classify_intent("summarize my docs please")
    assert intent == "chat"


@pytest.mark.asyncio
async def test_classify_intent_empty_query_returns_default():
    assert await classify_intent("") == "chat"
    assert await classify_intent("   ") == "chat"


@pytest.mark.asyncio
async def test_classify_intent_returns_llm_classification():
    with patch.object(ir, "_call_llm", new=AsyncMock(return_value='{"intent": "summarize"}')):
        assert await classify_intent("give me a recap of my docs") == "summarize"


@pytest.mark.asyncio
async def test_classify_intent_falls_back_on_rate_limit():
    with patch.object(
        ir,
        "_call_llm",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate"})),
    ):
        assert await classify_intent("anything") == "chat"


@pytest.mark.asyncio
async def test_classify_intent_falls_back_on_unexpected_error():
    with patch.object(ir, "_call_llm", new=AsyncMock(side_effect=RuntimeError("boom"))):
        assert await classify_intent("anything") == "chat"


@pytest.mark.asyncio
async def test_classify_intent_uses_extraction_model_and_json_mode(monkeypatch):
    monkeypatch.setattr(ir.settings, "groq_extraction_model", "vendor/route-x")
    fake = AsyncMock(return_value='{"intent": "chat"}')
    monkeypatch.setattr(ir, "chat_completion", fake)

    await classify_intent("anything")

    kwargs = fake.call_args.kwargs
    assert kwargs["model"] == "vendor/route-x"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0
    # Classification is a 3-way pick — no need for deep CoT. See #41.
    assert kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_classify_intent_handles_each_route_label(monkeypatch):
    for label in ("chat", "summarize", "explain_graph"):
        monkeypatch.setattr(ir, "_call_llm", AsyncMock(return_value=json.dumps({"intent": label})))
        assert await classify_intent(f"q for {label}") == label


def test_prompt_schema_example_is_valid_json():
    """Regression: the schema example inside the system prompt must itself
    parse as JSON. The old prompt used TypeScript-union syntax
    ('"chat" | "summarize" | "explain_graph"') which gpt-oss-120b tried to
    reproduce literally — Groq's server-side json_object validator then
    rejected the completion with 400 json_validate_failed. Prod incident
    2026-07-06, see #41."""
    obj_str = ir._extract_json_object(ir.SYSTEM_PROMPT)
    assert obj_str is not None, "no JSON object found in prompt"
    parsed = json.loads(obj_str)  # must not raise
    assert parsed.get("intent") in ("chat", "summarize", "explain_graph")
