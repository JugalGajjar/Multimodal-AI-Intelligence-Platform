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
    # gpt-oss reasoning models need explicit CoT budget management. "medium"
    # is enough to infer implicit relations from apposition/proximity without
    # burning the whole max_tokens on reasoning (which produced 0 rels in
    # prod). See #42.
    assert kwargs["reasoning_effort"] == "medium"
    # 8192 (was 4096 in #42, was 2048 before that) — entity-dense docs like
    # CVs surface 60-80+ entities and were filling the output budget with
    # entities alone, forcing "relationships": []. See #42a.
    assert kwargs["max_tokens"] == 8192


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


class TestSystemPromptContract:
    """The prompt must (a) parse as valid JSON in every schema example it
    contains, (b) not include the 'return empty lists if nothing notable'
    escape hatch that gave the model an easy out on slide/OCR text, and
    (c) name the domain-general failure modes (apposition, proximity,
    comparison verbs) that the #42 rewrite added. Test the contract, not
    the exact wording."""

    def test_all_schema_examples_are_valid_json(self):
        # The prompt embeds multiple JSON objects (schema shape + few-shot
        # example). Each must round-trip through json.loads — same regression
        # guard as intent_router / verifier (#41).
        prompt = extraction.SYSTEM_PROMPT
        offsets = [i for i, ch in enumerate(prompt) if ch == "{"]
        parsed_any = False
        for start in offsets:
            candidate = extraction._extract_json_object(prompt[start:])
            if candidate is None:
                continue
            # Skip TypeScript-union-y examples that were removed; the fixed
            # prompt should have every candidate parse cleanly.
            json.loads(candidate)
            parsed_any = True
        assert parsed_any, "no JSON objects found in prompt"

    def test_prompt_does_not_offer_safe_zero_escape(self):
        # The old "Return {\"entities\": [], \"relationships\": []} if
        # nothing notable" line gave conservative reasoning models an easy
        # out on OCR-noisy slide text. It must not reappear verbatim.
        low = extraction.SYSTEM_PROMPT.lower()
        assert "if nothing notable" not in low
        # But we DO want a scoped fallback for genuinely entity-free text.
        assert "no named entities" in low

    def test_prompt_names_implicit_relation_signals(self):
        # Domain-general failure modes the rewrite added.
        low = extraction.SYSTEM_PROMPT.lower()
        assert "apposition" in low or "parentheses" in low
        assert "juxtaposition" in low or "proximity" in low
        assert "comparison" in low or "outperforms" in low

    def test_prompt_stays_domain_neutral(self):
        # #42 explicitly avoided biasing toward research-specific relation
        # types like "author of" or "affiliated with" as required patterns
        # — those appear only as illustrative examples inside a bulleted
        # list of prose patterns. Guard against future edits that would
        # sneak in a domain-specific "you MUST extract author_of" rule.
        low = extraction.SYSTEM_PROMPT.lower()
        assert "medical" in low or "legal" in low or "any domain" in low

    def test_prompt_caps_description_length_to_avoid_starvation(self):
        # #42a — the prompt must instruct the model to keep entity
        # descriptions terse (2-6 words), because CV-style entity-dense
        # docs previously ate the whole output budget with sentence-long
        # descriptions and closed with "relationships": []. This rule is
        # what makes the token budget headroom usable at 60+ entities.
        low = extraction.SYSTEM_PROMPT.lower()
        assert "2-6 word" in low or "2-6 words" in low
        # The old "one short sentence" description ask must NOT reappear.
        assert "one short sentence" not in low
