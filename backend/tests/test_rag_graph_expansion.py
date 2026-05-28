"""Unit tests for substring-based entity matching against retrieved chunks."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.rag.graph_expansion import (
    GraphFact,
    GraphRelation,
    _build_haystack,
    _match_entities,
    expand_with_graph,
)
from app.rag.retrieval import RetrievedChunk


def _chunk(text: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        chunk_index=0,
        score=score,
        text=text,
    )


class TestBuildHaystack:
    def test_combines_query_and_chunk_text_lowercased(self):
        haystack = _build_haystack("What is Qdrant?", [_chunk("Qdrant uses cosine distance")])

        assert "qdrant" in haystack
        assert "cosine distance" in haystack
        # Original casing should not appear in the haystack
        assert "Qdrant" not in haystack


class TestMatchEntities:
    def test_matches_substrings_case_insensitive(self):
        haystack = "qdrant is the vector store and uses cosine distance"
        candidates = [
            {"name": "Qdrant", "type": "Technology"},
            {"name": "Cosine Distance", "type": "Concept"},
            {"name": "Neo4j", "type": "Technology"},
        ]

        matched = _match_entities(haystack, candidates)

        assert "Qdrant" in matched
        assert "Cosine Distance" in matched
        assert "Neo4j" not in matched

    def test_drops_names_shorter_than_3_chars(self):
        haystack = "we use ai pipelines"
        candidates = [{"name": "AI", "type": "Concept"}]

        assert _match_entities(haystack, candidates) == []

    def test_caps_total_matches(self):
        haystack = " ".join(f"entity{i}" for i in range(20))
        candidates = [{"name": f"entity{i}", "type": "Concept"} for i in range(20)]

        matched = _match_entities(haystack, candidates, max_matches=5)

        assert len(matched) == 5

    def test_longer_names_take_precedence(self):
        """If 'Cosine' and 'Cosine Distance' both match, the longer (more
        specific) name should appear in the matched list."""
        haystack = "qdrant uses cosine distance"
        candidates = [
            {"name": "Cosine", "type": "Concept"},
            {"name": "Cosine Distance", "type": "Concept"},
        ]

        matched = _match_entities(haystack, candidates)

        # Both still match (Cosine is a substring of "cosine distance" too),
        # but the longer name must appear first in the result order.
        assert matched.index("Cosine Distance") < matched.index("Cosine")


@pytest.mark.asyncio
async def test_expand_returns_empty_when_user_has_no_graph():
    with patch(
        "app.rag.graph_expansion.list_user_entities",
        new=AsyncMock(return_value=[]),
    ):
        result = await expand_with_graph(
            query="anything", chunks=[_chunk("anything")], user_id=uuid4()
        )

    assert result == []


@pytest.mark.asyncio
async def test_expand_returns_empty_when_no_names_match():
    with patch(
        "app.rag.graph_expansion.list_user_entities",
        new=AsyncMock(return_value=[{"name": "OnlyInGraph", "type": "Concept"}]),
    ):
        result = await expand_with_graph(
            query="nothing relevant",
            chunks=[_chunk("zero overlap")],
            user_id=uuid4(),
        )

    assert result == []


@pytest.mark.asyncio
async def test_expand_returns_facts_for_matched_entities():
    candidates = [
        {"name": "Qdrant", "type": "Technology"},
        {"name": "Cosine Distance", "type": "Concept"},
    ]
    fact_rows = [
        {
            "name": "Qdrant",
            "type": "Technology",
            "description": "vector DB",
            "relations": [
                {
                    "relation": "uses",
                    "direction": "out",
                    "other": "Cosine Distance",
                    "other_type": "Concept",
                    "other_description": "vector similarity metric",
                }
            ],
        },
    ]

    with (
        patch(
            "app.rag.graph_expansion.list_user_entities",
            new=AsyncMock(return_value=candidates),
        ),
        patch(
            "app.rag.graph_expansion.get_entity_facts",
            new=AsyncMock(return_value=fact_rows),
        ) as facts_call,
    ):
        result = await expand_with_graph(
            query="What does Qdrant use?",
            chunks=[_chunk("Qdrant uses cosine distance for similarity")],
            user_id=uuid4(),
        )

    assert len(result) == 1
    assert isinstance(result[0], GraphFact)
    assert result[0].name == "Qdrant"
    assert len(result[0].relations) == 1
    rel = result[0].relations[0]
    assert isinstance(rel, GraphRelation)
    assert rel.relation == "uses"
    assert rel.other == "Cosine Distance"

    # And the cypher lookup was called with both matched names (longest-first)
    called_names = facts_call.call_args.args[1]
    assert "Cosine Distance" in called_names
    assert "Qdrant" in called_names


@pytest.mark.asyncio
async def test_expand_drops_relations_with_missing_other_or_relation():
    candidates = [{"name": "Qdrant", "type": "Technology"}]
    fact_rows = [
        {
            "name": "Qdrant",
            "type": "Technology",
            "description": "",
            "relations": [
                {"relation": "uses", "direction": "out", "other": "Cosine Distance"},
                {"relation": None, "direction": "out", "other": "X"},  # dropped
                {"relation": "rel", "direction": "out", "other": None},  # dropped
            ],
        },
    ]
    with (
        patch(
            "app.rag.graph_expansion.list_user_entities",
            new=AsyncMock(return_value=candidates),
        ),
        patch(
            "app.rag.graph_expansion.get_entity_facts",
            new=AsyncMock(return_value=fact_rows),
        ),
    ):
        result = await expand_with_graph(
            query="qdrant", chunks=[_chunk("qdrant uses cosine distance")], user_id=uuid4()
        )

    assert len(result[0].relations) == 1
    assert result[0].relations[0].other == "Cosine Distance"
