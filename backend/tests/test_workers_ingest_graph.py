"""Unit tests for _ingest_graph's retry-on-transient-Groq-failure behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from app.graph.extraction import ExtractionOutcome
from app.graph.schema import ExtractionResult, GraphEntity
from app.workers import tasks


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
        patch("app.graph.neo4j_client.upsert_entity", new=AsyncMock()) as upsert,
        patch("app.graph.neo4j_client.upsert_relationship", new=AsyncMock()),
        # asyncio.sleep is called between attempts — no-op it so the test is fast.
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()),
    ):
        await tasks._ingest_graph(text="something", user_id="u-1", document_id="d-1")

    assert extract_mock.await_count == 3
    upsert.assert_awaited()
    # The one entity from the third attempt landed in Neo4j.
    assert upsert.await_count == 1


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
        await tasks._ingest_graph(text="hi", user_id="u-1", document_id="d-1")

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
        await tasks._ingest_graph(text="anything", user_id="u-1", document_id="d-1")

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
        patch("app.graph.neo4j_client.upsert_entity", new=AsyncMock()),
        patch("app.graph.neo4j_client.upsert_relationship", new=AsyncMock()),
        patch("app.workers.tasks.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        await tasks._ingest_graph(text="something", user_id="u-1", document_id="d-1")

    assert extract_mock.await_count == 1
    sleep.assert_not_awaited()
