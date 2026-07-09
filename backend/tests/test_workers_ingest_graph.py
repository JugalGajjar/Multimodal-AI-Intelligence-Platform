"""Unit tests for _ingest_graph's retry-on-transient-Groq-failure behavior."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.graph.extraction import ExtractionOutcome
from app.graph.schema import ExtractionResult, GraphEntity, GraphRelationship
from app.workers import tasks


def _fake_embed(dim: int = 4):
    """Return a stub for `app.embeddings.embed_texts` that emits `dim`-sized
    vectors, one per input string, deterministic by hash so identical names
    produce identical vectors (so semantic alignment doesn't collapse
    unrelated entities in fixtures)."""

    def _emb(texts):
        out = []
        for t in texts:
            h = hash(t) & 0xFFFF
            # Tiny "vector" that's L2-normalized enough for the assertions
            # this file cares about. Real bge vectors are 384-d.
            base = [((h >> i) & 0xF) / 15.0 for i in range(dim)]
            norm = sum(x * x for x in base) ** 0.5 or 1.0
            out.append([x / norm for x in base])
        return out

    return _emb


@contextmanager
def _semantic_mocks(semantic_candidates=None):
    """Stub the L3 semantic-alignment I/O so tests can focus on other logic.

    - `list_entity_semantic_candidates` returns an empty list by default.
    - `embed_texts` returns deterministic tiny vectors.
    Callers can pass `semantic_candidates` to seed the DB side.
    """
    fake_list = AsyncMock(return_value=semantic_candidates or [])
    fake_embed = MagicMock(side_effect=_fake_embed())
    with (
        patch(
            "app.graph.neo4j_client.list_entity_semantic_candidates",
            new=fake_list,
        ),
        patch("app.embeddings.embed_texts", new=fake_embed),
    ):
        yield fake_list, fake_embed


def _outcome_empty_transient() -> ExtractionOutcome:
    return ExtractionOutcome(
        result=ExtractionResult(entities=[], relationships=[]),
        transient_failure=True,
    )


def _outcome_empty_final() -> ExtractionOutcome:
    return ExtractionOutcome(
        result=ExtractionResult(entities=[], relationships=[]),
        transient_failure=False,
    )


def _outcome_with_entities() -> ExtractionOutcome:
    return ExtractionOutcome(
        result=ExtractionResult(
            entities=[GraphEntity(name="Qdrant", type="Technology", description="Vector DB")],
            relationships=[],
        ),
        transient_failure=False,
    )


@pytest.mark.asyncio
async def test_retries_transient_failure_until_it_succeeds():
    """Groq flakes twice with json_validate_failed, then returns entities.
    _ingest_graph must retry with backoff and write the eventual result."""
    extract_mock = AsyncMock(
        side_effect=[
            _outcome_empty_transient(),
            _outcome_empty_transient(),
            _outcome_with_entities(),
        ],
    )
    with (
        patch("app.graph.extraction.safe_extract_entities", new=extract_mock),
        patch("app.graph.neo4j_client.ensure_indexes", new=AsyncMock()),
        patch("app.graph.neo4j_client.list_entity_candidates", new=AsyncMock(return_value=[])),
        patch("app.graph.neo4j_client.upsert_entity", new=AsyncMock()) as upsert,
        patch("app.graph.neo4j_client.upsert_relationship", new=AsyncMock()),
        # asyncio.sleep is called between attempts — no-op it so the test is fast.
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()),
        _semantic_mocks(),
    ):
        await tasks._ingest_graph(chunks=["something"], user_id="u-1", document_id="d-1")

    assert extract_mock.await_count == 3
    upsert.assert_awaited()
    # The one entity from the third attempt landed in Neo4j.
    assert upsert.await_count == 1
    # Alignment layer added a name_lower kwarg — confirm it's populated.
    kwargs = upsert.await_args.kwargs
    assert kwargs["name"] == "Qdrant"
    assert kwargs["name_lower"] == "qdrant"
    # #43c: embedding kwarg goes through; new entity gets its computed vector.
    assert kwargs.get("embedding") is not None


@pytest.mark.asyncio
async def test_does_not_retry_when_extraction_is_genuinely_empty():
    """A well-formed empty extraction (transient_failure=False) should NOT
    trigger any retries — retrying would just spam Groq for docs with no
    real entities."""
    extract_mock = AsyncMock(return_value=_outcome_empty_final())
    with (
        patch("app.graph.extraction.safe_extract_entities", new=extract_mock),
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        await tasks._ingest_graph(chunks=["hi"], user_id="u-1", document_id="d-1")

    assert extract_mock.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts_of_transient_failure():
    """Three transient failures in a row → give up, log, no exception."""
    extract_mock = AsyncMock(return_value=_outcome_empty_transient())
    with (
        patch("app.graph.extraction.safe_extract_entities", new=extract_mock),
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        await tasks._ingest_graph(chunks=["anything"], user_id="u-1", document_id="d-1")

    assert extract_mock.await_count == tasks.GRAPH_EXTRACT_MAX_ATTEMPTS
    # Two backoff sleeps between the three attempts.
    assert sleep.await_count == tasks.GRAPH_EXTRACT_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_first_attempt_success_does_not_retry():
    """Happy path: first extract returns entities, no retry, no sleep."""
    extract_mock = AsyncMock(return_value=_outcome_with_entities())
    with (
        patch("app.graph.extraction.safe_extract_entities", new=extract_mock),
        patch("app.graph.neo4j_client.ensure_indexes", new=AsyncMock()),
        patch("app.graph.neo4j_client.list_entity_candidates", new=AsyncMock(return_value=[])),
        patch("app.graph.neo4j_client.upsert_entity", new=AsyncMock()),
        patch("app.graph.neo4j_client.upsert_relationship", new=AsyncMock()),
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()) as sleep,
        _semantic_mocks(),
    ):
        await tasks._ingest_graph(chunks=["something"], user_id="u-1", document_id="d-1")

    assert extract_mock.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_alignment_collapses_dupes_before_upsert():
    """#43a: extraction returns two entities that alias to the same
    canonical form + one that fuzzy-aliases to an existing DB entity.
    Upsert should be called ONCE for each unique canonical entity, not once
    per raw extraction entry, and relationship source/target should be
    rewritten through the alias mapping."""
    outcome = ExtractionOutcome(
        result=ExtractionResult(
            entities=[
                GraphEntity(name="Jugal Gajjar", type="Person", description="researcher"),
                # In-batch dup — should collapse via normalize_name.
                GraphEntity(name="jugal gajjar.", type="Person", description="dup"),
                # Fuzzy alias target of an existing DB entity ("gwu").
                GraphEntity(name="GWU", type="Organization", description="university"),
            ],
            relationships=[
                GraphRelationship(source="Jugal Gajjar", target="GWU", relation="works at"),
            ],
        ),
        transient_failure=False,
    )

    entity_ups = AsyncMock()
    rel_ups = AsyncMock()
    with (
        patch(
            "app.graph.extraction.safe_extract_entities",
            new=AsyncMock(return_value=outcome),
        ),
        patch("app.graph.neo4j_client.ensure_indexes", new=AsyncMock()),
        patch(
            "app.graph.neo4j_client.list_entity_candidates",
            new=AsyncMock(return_value=[("gwu", "Organization")]),
        ),
        patch("app.graph.neo4j_client.upsert_entity", new=entity_ups),
        patch("app.graph.neo4j_client.upsert_relationship", new=rel_ups),
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()),
        _semantic_mocks(),
    ):
        await tasks._ingest_graph(chunks=["anything"], user_id="u-1", document_id="d-1")

    # 3 raw entities → 2 aligned (jugal dup collapsed, GWU aliased into existing).
    assert entity_ups.await_count == 2
    written = {c.kwargs["name_lower"] for c in entity_ups.await_args_list}
    assert written == {"jugal gajjar", "gwu"}
    # Relationship survived and used the aliased canonical target ("gwu"),
    # with predicate normalized ("works at" → "affiliated with").
    assert rel_ups.await_count == 1
    rk = rel_ups.await_args.kwargs
    assert rk["source_lower"] == "jugal gajjar"
    assert rk["target_lower"] == "gwu"
    assert rk["relation"] == "affiliated with"


@pytest.mark.asyncio
async def test_semantic_alignment_aliases_to_existing_high_similarity(monkeypatch):
    """#43c: L1/L2 fuzzy misses (SFT vs Supervised Fine-Tuning has fuzz
    score way below 90) but L3 semantic catches — extracted 'Supervised
    Fine-Tuning' should alias to the existing 'sft' node when their
    embeddings clear the threshold."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "graph_semantic_threshold_same", 0.5)
    monkeypatch.setattr(settings, "graph_semantic_threshold_cross", 0.5)

    outcome = ExtractionOutcome(
        result=ExtractionResult(
            entities=[
                GraphEntity(
                    name="Supervised Fine-Tuning",
                    type="Concept",
                    description="SFT training phase",
                ),
            ],
            relationships=[],
        ),
        transient_failure=False,
    )

    # Existing DB entity: "sft" with an embedding. Our fake embedder is
    # deterministic-by-hash so we build a vector that MATCHES what the fake
    # will emit for the new "Supervised Fine-Tuning: SFT training phase"
    # input — then we can be sure similarity clears our lowered threshold.
    from app.graph.semantic_alignment import format_entity_text

    fake_embed_fn = _fake_embed()
    incoming_text = format_entity_text("Supervised Fine-Tuning", "SFT training phase")
    matching_vec = fake_embed_fn([incoming_text])[0]

    entity_ups = AsyncMock()
    rel_ups = AsyncMock()
    with (
        patch(
            "app.graph.extraction.safe_extract_entities",
            new=AsyncMock(return_value=outcome),
        ),
        patch("app.graph.neo4j_client.ensure_indexes", new=AsyncMock()),
        patch(
            "app.graph.neo4j_client.list_entity_candidates",
            new=AsyncMock(return_value=[]),  # L2 has no match for "supervised fine-tuning"
        ),
        patch(
            "app.graph.neo4j_client.list_entity_semantic_candidates",
            new=AsyncMock(return_value=[("sft", "Concept", matching_vec)]),
        ),
        patch("app.embeddings.embed_texts", new=MagicMock(side_effect=fake_embed_fn)),
        patch("app.graph.neo4j_client.upsert_entity", new=entity_ups),
        patch("app.graph.neo4j_client.upsert_relationship", new=rel_ups),
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()),
    ):
        await tasks._ingest_graph(chunks=["c"], user_id="u-1", document_id="d-1")

    # Aliased into the existing "sft" node — one upsert, keyed on "sft".
    assert entity_ups.await_count == 1
    kwargs = entity_ups.await_args.kwargs
    assert kwargs["name_lower"] == "sft"
    # Embedding on the aliased upsert is None — we never overwrite the
    # authoritative embedding on an existing node.
    assert kwargs.get("embedding") is None


def test_semantic_alignment_flag_default_is_on():
    """Guard: the L3 flag defaults on so the shipped behavior includes
    semantic alignment. The flag-off code path is a single-line guard;
    testing it via full-worker integration proved cross-test fragile under
    pytest's session-scoped async loop, so we skip that end-to-end assertion
    and lean on the unit-tested `find_semantic_alias` for correctness."""
    from app.core.config import settings

    assert settings.graph_semantic_align is True
    assert 0.0 < settings.graph_semantic_threshold_same <= 1.0
    assert 0.0 < settings.graph_semantic_threshold_cross <= 1.0
    # Cross-type threshold must be stricter than same-type (#43d).
    assert settings.graph_semantic_threshold_cross >= settings.graph_semantic_threshold_same
