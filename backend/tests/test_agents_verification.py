"""Unit tests for the verification agent."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents import verification as ver
from app.agents.verification import (
    ClaimVerdict,
    VerificationResult,
    verify_answer,
)
from app.rag.graph_expansion import GraphFact, GraphRelation
from app.rag.groq_chat import GroqChatError
from app.rag.retrieval import RetrievedChunk


def _chunk(text: str = "Qdrant uses cosine distance.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        chunk_index=0,
        score=0.9,
        text=text,
    )


def _fact() -> GraphFact:
    return GraphFact(
        name="Qdrant",
        type="Technology",
        description="vector DB",
        relations=[GraphRelation(relation="uses", other="Cosine Distance")],
    )


class TestScore:
    def test_empty_claims_scores_one(self):
        score, supported, unsupported = ver._score([])
        assert score == 1.0
        assert supported == 0
        assert unsupported == []

    def test_all_supported_scores_one(self):
        claims = [
            ClaimVerdict(text="a", support="supported"),
            ClaimVerdict(text="b", support="supported"),
        ]
        score, supported, _ = ver._score(claims)
        assert score == 1.0
        assert supported == 2

    def test_all_unsupported_scores_zero(self):
        claims = [ClaimVerdict(text="X", support="unsupported")]
        score, supported, unsupported = ver._score(claims)
        assert score == 0.0
        assert supported == 0
        assert unsupported == ["X"]

    def test_uncertain_counts_as_half(self):
        claims = [
            ClaimVerdict(text="a", support="supported"),
            ClaimVerdict(text="b", support="uncertain"),
        ]
        score, supported, unsupported = ver._score(claims)
        assert score == pytest.approx(0.75)
        assert supported == 1
        assert unsupported == []

    def test_mixed_scores_in_between(self):
        claims = [
            ClaimVerdict(text="a", support="supported"),
            ClaimVerdict(text="b", support="unsupported"),
            ClaimVerdict(text="c", support="unsupported"),
        ]
        score, supported, unsupported = ver._score(claims)
        assert score == pytest.approx(1 / 3, abs=0.001)
        assert supported == 1
        assert unsupported == ["b", "c"]


class TestVerdictThresholds:
    def test_no_claims_is_verified(self):
        assert ver._verdict_for(0.0, has_claims=False) == "verified"

    def test_high_score_is_verified(self):
        assert ver._verdict_for(0.95, has_claims=True) == "verified"

    def test_mid_score_is_partial(self):
        assert ver._verdict_for(0.6, has_claims=True) == "partial"

    def test_low_score_is_unsupported(self):
        assert ver._verdict_for(0.1, has_claims=True) == "unsupported"


class TestParseClaims:
    def test_well_formed_response_parses(self):
        raw = json.dumps(
            {
                "claims": [
                    {"text": "X uses Y", "support": "supported", "evidence": "[1]"},
                    {"text": "Z is blue", "support": "unsupported", "evidence": ""},
                ]
            }
        )
        out = ver._parse_claims(raw)
        assert len(out) == 2
        assert out[0].text == "X uses Y"
        assert out[1].support == "unsupported"

    def test_drops_items_with_invalid_support_label(self):
        raw = json.dumps(
            {"claims": [{"text": "a", "support": "MAYBE"}, {"text": "b", "support": "supported"}]}
        )
        out = ver._parse_claims(raw)
        assert len(out) == 1
        assert out[0].text == "b"

    def test_recovers_from_markdown_fenced_json(self):
        raw = '```json\n{"claims":[{"text":"a","support":"supported"}]}\n```'
        out = ver._parse_claims(raw)
        assert len(out) == 1

    def test_recovers_from_preamble_text(self):
        raw = 'Sure! Here you go:\n{"claims":[{"text":"a","support":"supported"}]}'
        out = ver._parse_claims(raw)
        assert len(out) == 1

    def test_non_json_returns_empty(self):
        assert ver._parse_claims("definitely not json") == []

    def test_missing_claims_key_returns_empty(self):
        assert ver._parse_claims('{"other": []}') == []


@pytest.mark.asyncio
async def test_verify_answer_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(ver.settings, "verification_enabled", False)
    result = await verify_answer(answer="x", chunks=[_chunk()], graph_facts=[])
    assert result.verdict == "skipped"
    assert "disabled" in result.skip_reason


@pytest.mark.asyncio
async def test_verify_answer_skipped_when_empty():
    result = await verify_answer(answer="   ", chunks=[_chunk()], graph_facts=[])
    assert result.verdict == "skipped"


@pytest.mark.asyncio
async def test_verify_answer_skipped_with_no_context_or_facts():
    result = await verify_answer(answer="some answer", chunks=[], graph_facts=[])
    assert result.verdict == "skipped"
    assert "no context" in result.skip_reason


@pytest.mark.asyncio
async def test_verify_answer_skipped_when_llm_rate_limited():
    with patch.object(
        ver,
        "_call_llm",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate"})),
    ):
        result = await verify_answer(
            answer="some answer",
            chunks=[_chunk()],
            graph_facts=[],
        )
    assert result.verdict == "skipped"
    assert "429" in result.skip_reason


@pytest.mark.asyncio
async def test_verify_answer_returns_verified_for_fully_supported():
    raw = json.dumps(
        {
            "claims": [
                {"text": "Qdrant uses cosine distance", "support": "supported", "evidence": "[1]"},
            ]
        }
    )
    with patch.object(ver, "_call_llm", new=AsyncMock(return_value=raw)):
        result = await verify_answer(
            answer="Qdrant uses cosine distance.",
            chunks=[_chunk()],
            graph_facts=[_fact()],
        )
    assert result.verdict == "verified"
    assert result.groundedness_score == 1.0
    assert result.total_claims == 1
    assert result.supported_claims == 1
    assert result.unsupported_claims == []


@pytest.mark.asyncio
async def test_verify_answer_returns_partial_for_mostly_supported():
    raw = json.dumps(
        {
            "claims": [
                {"text": "Qdrant uses cosine distance", "support": "supported"},
                {"text": "Qdrant was invented in 1987", "support": "unsupported"},
            ]
        }
    )
    with patch.object(ver, "_call_llm", new=AsyncMock(return_value=raw)):
        result = await verify_answer(
            answer="Qdrant uses cosine distance. Qdrant was invented in 1987.",
            chunks=[_chunk()],
            graph_facts=[],
        )
    # 1/2 supported = 0.5 → at the partial threshold → partial
    assert result.verdict == "partial"
    assert result.groundedness_score == 0.5
    assert result.unsupported_claims == ["Qdrant was invented in 1987"]


@pytest.mark.asyncio
async def test_verify_answer_returns_unsupported_for_mostly_unsupported():
    raw = json.dumps(
        {
            "claims": [
                {"text": "claim a", "support": "unsupported"},
                {"text": "claim b", "support": "unsupported"},
                {"text": "claim c", "support": "supported"},
            ]
        }
    )
    with patch.object(ver, "_call_llm", new=AsyncMock(return_value=raw)):
        result = await verify_answer(
            answer="claim a. claim b. claim c.",
            chunks=[_chunk()],
            graph_facts=[],
        )
    assert result.verdict == "unsupported"
    assert result.groundedness_score < 0.5


@pytest.mark.asyncio
async def test_verify_answer_verified_when_zero_claims_extracted():
    """Vacuously verified — a non-factual answer has nothing to invalidate."""
    raw = json.dumps({"claims": []})
    with patch.object(ver, "_call_llm", new=AsyncMock(return_value=raw)):
        result = await verify_answer(
            answer="I will explain this.",
            chunks=[_chunk()],
            graph_facts=[],
        )
    assert result.verdict == "verified"
    assert result.total_claims == 0


@pytest.mark.asyncio
async def test_verify_answer_uses_extraction_model_and_json_mode(monkeypatch):
    """Verification must call the configured extraction model (json-reliable),
    not the reasoning model that occasionally returns malformed JSON."""
    monkeypatch.setattr(ver.settings, "groq_extraction_model", "vendor/verify-x")
    fake = AsyncMock(return_value='{"claims": []}')
    monkeypatch.setattr(ver, "chat_completion", fake)

    await verify_answer(answer="x", chunks=[_chunk()], graph_facts=[])

    kwargs = fake.call_args.kwargs
    assert kwargs["model"] == "vendor/verify-x"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0


def test_to_dict_round_trips_a_typical_result():
    r = VerificationResult(
        verdict="partial",
        groundedness_score=0.66666,
        total_claims=3,
        supported_claims=2,
        unsupported_claims=["bad"],
    )
    out = ver.to_dict(r)
    assert out["verdict"] == "partial"
    assert out["groundedness_score"] == 0.667
    assert out["total_claims"] == 3
    assert out["supported_claims"] == 2
    assert out["unsupported_claims"] == ["bad"]
