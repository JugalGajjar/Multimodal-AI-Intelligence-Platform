"""Unit tests for the LLM-driven entity extraction module.

Two paths tested:

- **Map-reduce** (#43, default): per-chunk two-pass. Tested via public
  `extract_entities_from_chunks` and `safe_extract_entities`.
- **Legacy single-shot** (pre-#43, feature-flag rollback): tested with an
  explicit `legacy_mode` fixture that flips `graph_extraction_map_reduce`
  off. Delete when the flag comes out.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.graph import extraction
from app.graph.schema import ExtractionResult
from app.rag.groq_chat import GroqChatError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_mode(monkeypatch):
    """Toggle the map-reduce feature flag off so the caller's assertions
    exercise the pre-#43 single-shot behavior (retry logic, MAX_INPUT_CHARS,
    single-call schema). Legacy tests opt in via this fixture."""
    monkeypatch.setattr(settings, "graph_extraction_map_reduce", False)


@pytest.fixture
def no_reconcile(monkeypatch):
    """Disable Phase 3 reconciliation. Map-reduce tests that assert on exact
    LLM call counts opt in so a reconciliation pass doesn't fire extra calls."""
    monkeypatch.setattr(settings, "graph_extraction_reconcile", False)


# ---------------------------------------------------------------------------
# Empty-input / smoke
# ---------------------------------------------------------------------------


async def test_empty_text_returns_empty_without_llm_call():
    with patch("app.graph.extraction.chat_completion", new=AsyncMock()) as fake_call:
        result = await extraction.extract_entities("   ")

    assert result.entities == []
    fake_call.assert_not_called()


async def test_empty_chunks_returns_empty_without_llm_call():
    with patch("app.graph.extraction.chat_completion", new=AsyncMock()) as fake_call:
        result = await extraction.extract_entities_from_chunks([" ", ""])

    assert result == ExtractionResult()
    fake_call.assert_not_called()


# ---------------------------------------------------------------------------
# JSON recovery — module-level, path-agnostic
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Legacy single-shot path — behind feature flag
# ---------------------------------------------------------------------------


async def test_legacy_parses_well_formed_json_and_normalizes(legacy_mode):
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


async def test_legacy_uses_json_response_format(legacy_mode, monkeypatch):
    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    await extraction.extract_entities("some text")

    kwargs = fake.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.0
    # Legacy path uses the pre-#43 tuning: medium reasoning, 5120 max_tokens
    # (safe under Groq's free-tier 8K TPM per-request ceiling).
    assert kwargs["reasoning_effort"] == "medium"
    assert kwargs["max_tokens"] == 5120


async def test_legacy_non_json_response_returns_empty(legacy_mode):
    with patch(
        "app.graph.extraction.chat_completion",
        new=AsyncMock(return_value="hi I am not json"),
    ):
        result = await extraction.extract_entities("anything")
    assert result == ExtractionResult()


async def test_legacy_malformed_schema_returns_empty(legacy_mode):
    bad = json.dumps({"entities": [{"foo": "bar"}]})
    with patch("app.graph.extraction.chat_completion", new=AsyncMock(return_value=bad)):
        result = await extraction.extract_entities("anything")
    assert result == ExtractionResult()


async def test_legacy_truncates_long_input(legacy_mode, monkeypatch):
    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    long_text = "x" * 50_000
    await extraction.extract_entities(long_text)

    user_msg = fake.call_args.kwargs["messages"][1]["content"]
    assert len(user_msg) <= extraction.MAX_INPUT_CHARS


async def test_legacy_retry_on_per_minute_429_then_succeeds(legacy_mode, monkeypatch):
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
    assert 4.5 < slept[0] < 6.5


async def test_legacy_does_not_retry_on_per_day_429(legacy_mode, monkeypatch):
    err = GroqChatError(
        429,
        {"error": {"message": "Rate limit reached. Please try again in 14m20.112s."}},
    )
    fake = AsyncMock(side_effect=err)
    monkeypatch.setattr("app.graph.extraction._call_llm", fake)
    monkeypatch.setattr("app.graph.extraction.asyncio.sleep", AsyncMock())

    outcome = await extraction.safe_extract_entities(["anything"])
    # safe_extract wraps errors — expect empty result, transient flag set.
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is True
    assert fake.await_count == 1


async def test_legacy_retries_once_on_json_validate_400(legacy_mode, monkeypatch):
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


async def test_legacy_uses_extraction_model_not_reasoning_model(legacy_mode, monkeypatch):
    from types import SimpleNamespace

    stub = SimpleNamespace(
        groq_extraction_model="vendor/extraction-x",
        groq_reasoning_model="vendor/chat-y",
    )
    monkeypatch.setattr("app.graph.extraction.settings", stub)

    fake = AsyncMock(return_value='{"entities": [], "relationships": []}')
    monkeypatch.setattr("app.graph.extraction.chat_completion", fake)

    await extraction._extract_entities_single_shot("anything")
    assert fake.call_args.kwargs["model"] == "vendor/extraction-x"


# ---------------------------------------------------------------------------
# Map-reduce path — the new default
# ---------------------------------------------------------------------------


def _entity_json(*entities: tuple[str, str]) -> str:
    """Build a Pass 1 JSON response containing the given (name, type) pairs."""
    return json.dumps(
        {"entities": [{"name": n, "type": t, "description": "tag"} for n, t in entities]}
    )


def _relation_json(*triples: tuple[str, str, str]) -> str:
    """Build a Pass 2 JSON response containing the given (source, target, relation) triples."""
    return json.dumps(
        {"relationships": [{"source": s, "target": t, "relation": r} for s, t, r in triples]}
    )


async def test_map_reduce_single_chunk_end_to_end(monkeypatch):
    call_i = {"n": 0}

    async def fake_chat(**_kwargs):
        call_i["n"] += 1
        return (
            _entity_json(("Qdrant", "Technology"), ("Cosine", "Concept"))
            if call_i["n"] == 1
            else _relation_json(("Qdrant", "Cosine", "uses"))
        )

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    result = await extraction.extract_entities_from_chunks(["some chunk text"])
    assert {e.name for e in result.entities} == {"Qdrant", "Cosine"}
    assert len(result.relationships) == 1
    assert result.relationships[0].source == "Qdrant"
    assert result.relationships[0].target == "Cosine"


async def test_map_reduce_multiple_chunks_merged(monkeypatch):
    # Chunk 1 returns entities/rels; Chunk 2 returns different ones. Final
    # merged result should contain both chunks' contributions (dedup + fuzzy
    # alignment happens later in align_batch, not here).
    plan = [
        _entity_json(("Alice", "Person"), ("Acme", "Organization")),
        _relation_json(("Alice", "Acme", "works at")),
        _entity_json(("Bob", "Person"), ("Acme", "Organization")),
        _relation_json(("Bob", "Acme", "works at")),
    ]
    call_i = {"n": 0}

    async def fake_chat(**_kwargs):
        i = call_i["n"]
        call_i["n"] += 1
        return plan[i]

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    result = await extraction.extract_entities_from_chunks(["chunk 1", "chunk 2"])
    names = [e.name for e in result.entities]
    # Merge is a concatenation — dedup is the align_batch layer's job.
    assert names.count("Alice") == 1
    assert names.count("Bob") == 1
    assert names.count("Acme") == 2  # appears in both chunks pre-alignment
    assert len(result.relationships) == 2


async def test_map_reduce_skips_pass2_when_pass1_empty(monkeypatch):
    call_log: list[str] = []

    async def fake_chat(*, messages, **_kwargs):
        # First message content is the system prompt; use it to identify pass.
        system = messages[0]["content"]
        if "listing the named entities" in system:
            call_log.append("pass1")
            return json.dumps({"entities": []})
        call_log.append("pass2")
        return json.dumps({"relationships": []})

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    result = await extraction.extract_entities_from_chunks(["chunk"])
    assert result.entities == []
    assert result.relationships == []
    # Pass 2 must NOT be called when there are no entities to relate.
    assert call_log == ["pass1"]


async def test_map_reduce_isolates_pass1_failure_to_one_chunk(monkeypatch):
    """One chunk's Pass 1 raises — the other chunk should still land its
    entities. The whole doc must not fail because of one 429."""
    plan_iter = iter(
        [
            GroqChatError(429, {"detail": "rate"}),  # chunk 1 pass1
            # chunk 2 pass1
            _entity_json(("Bob", "Person")),
            _relation_json(),  # chunk 2 pass2
        ]
    )

    async def fake_chat(**_kwargs):
        nxt = next(plan_iter)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    result = await extraction.extract_entities_from_chunks(["c1", "c2"])
    # Chunk 2's entity survived; chunk 1 silently dropped.
    assert [e.name for e in result.entities] == ["Bob"]


async def test_map_reduce_pass2_failure_keeps_pass1_entities(monkeypatch):
    """If Pass 2 fails for a chunk, the Pass 1 entities from that chunk
    still merge into the union — better half than nothing."""
    plan_iter = iter(
        [
            _entity_json(("Alice", "Person")),  # pass1 ok
            GroqChatError(429, {"detail": "rate"}),  # pass2 fails
        ]
    )

    async def fake_chat(**_kwargs):
        nxt = next(plan_iter)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    result = await extraction.extract_entities_from_chunks(["c"])
    assert [e.name for e in result.entities] == ["Alice"]
    assert result.relationships == []


async def test_map_reduce_pass2_drops_fabricated_source_target(monkeypatch):
    """The Pass 2 prompt tells the model to only use names from the entity
    list. If it hallucinates a source/target not in the list, we drop it
    at parse time."""
    plan = [
        _entity_json(("Alice", "Person")),
        _relation_json(
            ("Alice", "Bob", "knows"),  # Bob not in entities → drop
            ("Alice", "Alice", "same"),  # self ref, but alignment layer catches this later
        ),
    ]
    call_i = {"n": 0}

    async def fake_chat(**_kwargs):
        i = call_i["n"]
        call_i["n"] += 1
        return plan[i]

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    result = await extraction.extract_entities_from_chunks(["c"])
    # "Alice → Bob" was dropped because Bob isn't a listed entity.
    for rel in result.relationships:
        assert rel.target != "Bob"


async def test_map_reduce_pass_kwargs(monkeypatch):
    """Both passes must configure Groq the same way: JSON mode, temp 0,
    reasoning_effort=medium, max_tokens=PASS_MAX_TOKENS."""
    captured: list[dict] = []

    async def fake_chat(**kwargs):
        captured.append(kwargs)
        if "listing the named entities" in kwargs["messages"][0]["content"]:
            return _entity_json(("X", "Concept"))
        return _relation_json()

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    await extraction.extract_entities_from_chunks(["c"])
    assert len(captured) == 2
    for kw in captured:
        assert kw["temperature"] == 0.0
        assert kw["reasoning_effort"] == "medium"
        assert kw["response_format"] == {"type": "json_object"}
        assert kw["max_tokens"] == extraction.PASS_MAX_TOKENS


async def test_map_reduce_concurrency_defaults_to_key_pool_size(monkeypatch):
    """Concurrency should default to the Groq key-pool size so each in-flight
    call naturally lands on its own key. A 3-key pool → semaphore(3)."""
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "a,b,c")

    # Fall through to check the module-level default computation.
    assert extraction._default_concurrency() == 3

    monkeypatch.setattr(settings, "groq_api_keys", "a,b")
    assert extraction._default_concurrency() == 2

    monkeypatch.setattr(settings, "groq_api_keys", "")
    monkeypatch.setattr(settings, "groq_api_key", "single")
    # Single-key pool → fallback of 3 (modest concurrency, no TPM contention
    # since one key handles them all sequentially at the SDK layer).
    assert extraction._default_concurrency() == 3


async def test_map_reduce_semaphore_bounds_concurrent_llm_calls(monkeypatch):
    """Semaphore scope B: at most N LLM calls in flight at any moment across
    the whole batch, regardless of chunk count."""
    concurrent_now = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_chat(*, messages, **_kwargs):
        nonlocal concurrent_now, peak
        async with lock:
            concurrent_now += 1
            peak = max(peak, concurrent_now)
        await asyncio.sleep(0.01)
        async with lock:
            concurrent_now -= 1
        if "listing the named entities" in messages[0]["content"]:
            return _entity_json(("E", "Concept"))
        return _relation_json()

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    await extraction.extract_entities_from_chunks(
        [f"chunk{i}" for i in range(8)],
        concurrency=2,
    )
    assert peak <= 2


# ---------------------------------------------------------------------------
# safe_extract_entities
# ---------------------------------------------------------------------------


async def test_safe_extract_empty_chunks_is_not_transient():
    outcome = await extraction.safe_extract_entities([])
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is False


async def test_safe_extract_all_chunks_transient_flags_transient(monkeypatch):
    err = GroqChatError(429, {"detail": "rate"})
    monkeypatch.setattr("app.graph.extraction.chat_completion", AsyncMock(side_effect=err))
    outcome = await extraction.safe_extract_entities(["c1", "c2"])
    # Every chunk's pass1 failed transiently → outcome is transient.
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is True


async def test_safe_extract_partial_success_is_not_transient(monkeypatch):
    """One chunk 429s, another succeeds → NOT transient; partial results
    are useful and re-running would just spam Groq."""
    plan_iter = iter(
        [
            GroqChatError(429, {"detail": "rate"}),  # c1 pass1
            _entity_json(("Alice", "Person")),  # c2 pass1
            _relation_json(),  # c2 pass2
        ]
    )

    async def fake_chat(**_kwargs):
        nxt = next(plan_iter)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)

    outcome = await extraction.safe_extract_entities(["c1", "c2"])
    assert [e.name for e in outcome.result.entities] == ["Alice"]
    assert outcome.transient_failure is False


async def test_safe_extract_swallows_unexpected_errors(monkeypatch):
    monkeypatch.setattr(
        "app.graph.extraction.chat_completion", AsyncMock(side_effect=RuntimeError("boom"))
    )
    outcome = await extraction.safe_extract_entities(["c1"])
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is True


async def test_safe_extract_legacy_path(legacy_mode, monkeypatch):
    """With the flag off, safe_extract_entities takes chunks list, joins,
    and runs the legacy single-shot path (same behavior as pre-#43)."""
    monkeypatch.setattr(
        "app.graph.extraction.chat_completion",
        AsyncMock(return_value='{"entities": [], "relationships": []}'),
    )
    outcome = await extraction.safe_extract_entities(["chunk one", "chunk two"])
    assert outcome.result == ExtractionResult()
    assert outcome.transient_failure is False


# ---------------------------------------------------------------------------
# Prompt contracts (both new prompts + legacy)
# ---------------------------------------------------------------------------


class TestPromptContract:
    """Guard against regressions in the extraction prompts. Test the
    contract (JSON validity, domain-neutral language, key rules), not
    exact wording."""

    def test_entities_prompt_schema_is_valid_json(self):
        obj = extraction._extract_json_object(extraction.SYSTEM_PROMPT_ENTITIES)
        assert obj is not None
        parsed = json.loads(obj)
        assert isinstance(parsed.get("entities"), list)

    def test_relations_prompt_schema_is_valid_json(self):
        # The relations prompt has multiple JSON blocks (schema + example).
        # Both must parse.
        prompt = extraction.SYSTEM_PROMPT_RELATIONS
        offsets = [i for i, ch in enumerate(prompt) if ch == "{"]
        parsed_any = False
        for start in offsets:
            candidate = extraction._extract_json_object(prompt[start:])
            if candidate is None:
                continue
            json.loads(candidate)
            parsed_any = True
        assert parsed_any

    def test_entities_prompt_skips_date_entities(self):
        low = extraction.SYSTEM_PROMPT_ENTITIES.lower()
        # Explicit rule — general modeling principle, not domain-specific.
        assert "date entity" in low or "not create a date" in low
        # Date type must NOT appear in the allowed-types line.
        allowed_line = next(
            line
            for line in extraction.SYSTEM_PROMPT_ENTITIES.splitlines()
            if "Allowed entity types" in line
        )
        assert "Date" not in allowed_line

    def test_entities_prompt_caps_description_length(self):
        assert "2-6 word" in extraction.SYSTEM_PROMPT_ENTITIES.lower()

    def test_entities_prompt_stays_domain_neutral(self):
        low = extraction.SYSTEM_PROMPT_ENTITIES.lower()
        assert "medical" in low or "legal" in low or "any domain" in low

    def test_relations_prompt_forbids_fabricated_entity_names(self):
        low = extraction.SYSTEM_PROMPT_RELATIONS.lower()
        assert "must both be names that appear" in low or "do not invent" in low

    def test_relations_prompt_names_implicit_relation_signals(self):
        low = extraction.SYSTEM_PROMPT_RELATIONS.lower()
        assert "apposition" in low or "parentheses" in low
        assert "juxtaposition" in low or "proximity" in low
        assert "comparison" in low or "outperforms" in low

    def test_legacy_prompt_still_valid(self):
        """The kept-for-rollback SYSTEM_PROMPT must remain a valid combined
        entities+relations prompt with parseable JSON schema examples."""
        prompt = extraction.SYSTEM_PROMPT
        assert "entities" in prompt.lower()
        assert "relationships" in prompt.lower()
        # First JSON block should be the schema.
        obj = extraction._extract_json_object(prompt)
        assert obj is not None
        parsed = json.loads(obj)
        assert "entities" in parsed
        assert "relationships" in parsed


# ---------------------------------------------------------------------------
# Phase 3 — cross-chunk relation reconciliation (#43b)
# ---------------------------------------------------------------------------


class TestCooccurrenceScore:
    """Deterministic scoring — no async, no LLM."""

    def test_same_chunk_scores_three(self):
        assert extraction._cooccurrence_score(frozenset({0}), frozenset({0})) == 3

    def test_adjacent_chunks_score_two(self):
        assert extraction._cooccurrence_score(frozenset({0}), frozenset({1})) == 2

    def test_nearby_scores_one(self):
        assert extraction._cooccurrence_score(frozenset({0}), frozenset({3})) == 1

    def test_far_apart_scores_zero(self):
        assert extraction._cooccurrence_score(frozenset({0}), frozenset({10})) == 0

    def test_multiple_pairings_accumulate(self):
        # a in chunks {0,1}, b in chunks {0,2}
        #   pairings: (0,0)=+3, (0,2)=+1, (1,0)=+2, (1,2)=+2 → 8
        s = extraction._cooccurrence_score(frozenset({0, 1}), frozenset({0, 2}))
        assert s == 8


class TestGatherSnippets:
    def test_picks_up_to_max(self):
        chunks = ["one", "two", "three", "four", "five"]
        out = extraction._gather_snippets(
            chunks, frozenset({0, 2, 4}), max_snippets=2, max_chars=100
        )
        # Sorted-then-take: {0, 2, 4} → [0, 2] → "one" then "three".
        assert "one" in out and "three" in out
        assert "five" not in out

    def test_truncates_each_snippet(self):
        chunks = ["A" * 1000]
        out = extraction._gather_snippets(chunks, frozenset({0}), max_snippets=1, max_chars=50)
        # Snippet trimmed to 50 chars.
        assert len(out.strip()) <= 50

    def test_skips_out_of_range_indices(self):
        chunks = ["only"]
        # Index 5 doesn't exist — should be silently dropped, not raise.
        out = extraction._gather_snippets(chunks, frozenset({0, 5}), max_snippets=5, max_chars=100)
        assert "only" in out


class TestReconciliation:
    """Reconciliation-phase behavior when it actually fires — requires
    ≥2 unique entities across chunks, and pairs with score>0."""

    async def test_disabled_flag_skips_reconciliation(self, no_reconcile, monkeypatch):
        # Configure a scenario that WOULD produce candidates, then flip the
        # flag off — no extra LLM calls should fire.
        plan = iter(
            [
                _entity_json(("A", "Person"), ("B", "Organization")),  # c0 pass1
                _relation_json(),  # c0 pass2 (empty)
                _entity_json(("C", "Person")),  # c1 pass1
                _relation_json(),  # c1 pass2
            ]
        )
        call_count = {"n": 0}

        async def fake_chat(**_kwargs):
            call_count["n"] += 1
            return next(plan)

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        await extraction.extract_entities_from_chunks(["c0", "c1"])
        # Exactly 4 calls — 2 chunks × 2 passes. No reconciliation.
        assert call_count["n"] == 4

    async def test_reconciliation_fires_for_cross_chunk_dangling_pair(self, monkeypatch):
        """Alice in chunk 0, Bob in chunk 1 → they never share a chunk, so
        Pass 2 can't relate them. Reconciliation should catch it."""

        async def fake_chat(*, messages, **_kwargs):
            system = messages[0]["content"]
            user = messages[1]["content"]
            if "listing the named entities" in system:
                # Pass 1 for whichever chunk we're on.
                if "chunk zero" in user:
                    return _entity_json(("Alice", "Person"))
                return _entity_json(("Bob", "Person"))
            if "every relation the passage supports" in system:
                # Pass 2 — no relations (Alice never mentioned Bob directly).
                return json.dumps({"relationships": []})
            # Reconciliation prompt — assert we got asked about Alice/Bob,
            # then affirm.
            assert "Alice" in user and "Bob" in user
            return json.dumps({"relation": "knows", "direction": "AB"})

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        result = await extraction.extract_entities_from_chunks(["chunk zero", "chunk one"])
        # The reconciliation-emitted relation lands in the union.
        assert any(
            r.source == "Alice" and r.target == "Bob" and r.relation == "knows"
            for r in result.relationships
        )

    async def test_reconciliation_respects_direction_ba(self, monkeypatch):
        """When the model returns direction='BA', source/target are flipped
        relative to the pair's (A, B) assignment. Pairs are enumerated by
        sorted name_lower, so 'alice' < 'book' → A=Alice, B=Book, BA means
        Book → Alice."""

        async def fake_chat(*, messages, **_kwargs):
            system = messages[0]["content"]
            user = messages[1]["content"]
            if "listing the named entities" in system:
                # Alice in c0, Book in c1.
                return (
                    _entity_json(("Alice", "Person"))
                    if "c0" in user
                    else _entity_json(("Book", "Product"))
                )
            if "every relation the passage supports" in system:
                return json.dumps({"relationships": []})
            return json.dumps({"relation": "authored by", "direction": "BA"})

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        result = await extraction.extract_entities_from_chunks(["c0", "c1"])
        # Sorted keys: alice, book → A=Alice, B=Book. BA flips → source=Book,
        # target=Alice. Relation "authored by" reads "Book authored by Alice",
        # matching the direction flip.
        assert any(
            r.source == "Book" and r.target == "Alice" and r.relation == "authored by"
            for r in result.relationships
        )

    async def test_reconciliation_skips_pairs_pass2_already_emitted(self, monkeypatch):
        """If Pass 2 already emitted (A, B), reconciliation must NOT re-ask
        about that pair — waste of a Groq call."""

        async def fake_chat(*, messages, **_kwargs):
            system = messages[0]["content"]
            user = messages[1]["content"]
            if "listing the named entities" in system:
                return _entity_json(("A", "Person"), ("B", "Organization"))
            if "every relation the passage supports" in system:
                return _relation_json(("A", "B", "works at"))
            # Reconciliation must not be reached — pair already handled.
            # If it does reach here, blow up so the test catches the leak.
            raise AssertionError(f"unexpected reconciliation call: {user!r}")

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        result = await extraction.extract_entities_from_chunks(["chunk"])
        assert len(result.relationships) == 1

    async def test_reconciliation_null_response_adds_no_relation(self, monkeypatch):
        """When the model returns {"relation": null}, no relation is added
        even though the pair was asked about."""

        async def fake_chat(*, messages, **_kwargs):
            system = messages[0]["content"]
            if "listing the named entities" in system:
                user = messages[1]["content"]
                return (
                    _entity_json(("A", "Person")) if "c0" in user else _entity_json(("B", "Person"))
                )
            if "every relation the passage supports" in system:
                return json.dumps({"relationships": []})
            # Reconciliation — explicit "no relation".
            return json.dumps({"relation": None})

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        result = await extraction.extract_entities_from_chunks(["c0", "c1"])
        # Pass 2 produced no rels; reconciliation returned null; total = 0.
        assert result.relationships == []

    async def test_reconciliation_bounded_by_top_k(self, monkeypatch):
        """Only top_k candidate pairs get an LLM call, no matter how many
        unrelated pairs exist."""
        monkeypatch.setattr(settings, "graph_extraction_reconcile_top_k", 2)

        # 4 chunks, each with one unique entity → all pairs are dangling.
        # C(4,2) = 6 candidate pairs. With top_k=2, only 2 reconcile calls.
        entity_names = ["A", "B", "C", "D"]

        reconcile_calls = {"n": 0}

        async def fake_chat(*, messages, **_kwargs):
            system = messages[0]["content"]
            user = messages[1]["content"]
            if "listing the named entities" in system:
                # Return the entity for whichever chunk we're on.
                for name in entity_names:
                    if f"chunk {name}" in user:
                        return _entity_json((name, "Concept"))
                return _entity_json(())
            if "every relation the passage supports" in system:
                return json.dumps({"relationships": []})
            # Reconciliation
            reconcile_calls["n"] += 1
            return json.dumps({"relation": None})

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        await extraction.extract_entities_from_chunks([f"chunk {n}" for n in entity_names])
        # At most top_k=2 reconciliation calls, not 6.
        assert reconcile_calls["n"] <= 2

    async def test_reconciliation_upstream_failure_does_not_crash(self, monkeypatch):
        """A 429 during reconciliation drops that pair silently — other work
        still lands. Whole batch must not fail."""

        async def fake_chat(*, messages, **_kwargs):
            system = messages[0]["content"]
            if "listing the named entities" in system:
                user = messages[1]["content"]
                return (
                    _entity_json(("A", "Person")) if "c0" in user else _entity_json(("B", "Person"))
                )
            if "every relation the passage supports" in system:
                return json.dumps({"relationships": []})
            raise GroqChatError(429, {"detail": "rate"})

        monkeypatch.setattr("app.graph.extraction.chat_completion", fake_chat)
        result = await extraction.extract_entities_from_chunks(["c0", "c1"])
        # Reconciliation failed; entities from Pass 1 still land.
        assert {e.name for e in result.entities} == {"A", "B"}


class TestReconciliationPromptContract:
    def test_reconcile_prompt_schema_is_valid_json(self):
        obj = extraction._extract_json_object(extraction.SYSTEM_PROMPT_RECONCILE)
        assert obj is not None
        parsed = json.loads(obj)
        assert "relation" in parsed
        assert "direction" in parsed

    def test_reconcile_prompt_requires_null_on_uncertain(self):
        low = extraction.SYSTEM_PROMPT_RECONCILE.lower()
        assert "null" in low
        assert "if uncertain" in low or "if no relation" in low

    def test_reconcile_prompt_forbids_common_knowledge_fabrication(self):
        low = extraction.SYSTEM_PROMPT_RECONCILE.lower()
        assert "common knowledge" in low or "do not invent" in low

    def test_reconcile_prompt_is_domain_neutral(self):
        low = extraction.SYSTEM_PROMPT_RECONCILE.lower()
        assert "medical" in low or "legal" in low or "any domain" in low

    def test_reconcile_prompt_flags_co_mention_as_strong_signal(self):
        """#43d: same-chunk co-mention is a strong signal — the prompt tells
        the model to bias TOWARD emitting a relation for co-mentioned pairs
        even without an explicit verb (byline, author list, apposition).
        Fixes the Person↔Person co-authorship gap where Jugal ↔ Kamalasankari
        stayed unlinked because reconciliation was too conservative."""
        low = extraction.SYSTEM_PROMPT_RECONCILE.lower()
        # Must name the specific co-mention patterns that generalize across
        # domains — bylines, author lists, apposition, entity lists.
        assert "co-appear" in low or "co-mention" in low or "same snippet" in low
        assert "byline" in low or "author list" in low or "apposition" in low
