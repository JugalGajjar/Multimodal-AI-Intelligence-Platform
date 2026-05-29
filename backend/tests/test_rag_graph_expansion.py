"""Unit tests for graph expansion (name-match + doc-scoped)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.rag.graph_expansion import (
    GraphFact,
    GraphRelation,
    _build_haystack,
    _document_ids_from_chunks,
    _match_entities,
    _merge_unique,
    expand_with_graph,
)
from app.rag.retrieval import RetrievedChunk


def _chunk(text: str, *, document_id: str | None = None, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        document_id=document_id or str(uuid4()),
        chunk_index=0,
        score=score,
        text=text,
    )


class TestBuildHaystack:
    def test_combines_query_and_chunk_text_lowercased(self):
        haystack = _build_haystack("What is Qdrant?", [_chunk("Qdrant uses cosine distance")])

        assert "qdrant" in haystack
        assert "cosine distance" in haystack
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
        haystack = "qdrant uses cosine distance"
        candidates = [
            {"name": "Cosine", "type": "Concept"},
            {"name": "Cosine Distance", "type": "Concept"},
        ]

        matched = _match_entities(haystack, candidates)

        assert matched.index("Cosine Distance") < matched.index("Cosine")


class TestDocumentIdsFromChunks:
    def test_collects_unique_in_order(self):
        chunks = [
            _chunk("a", document_id="doc-1"),
            _chunk("b", document_id="doc-2"),
            _chunk("c", document_id="doc-1"),  # dup
            _chunk("d", document_id="doc-3"),
        ]

        assert _document_ids_from_chunks(chunks) == ["doc-1", "doc-2", "doc-3"]

    def test_empty_chunks_returns_empty(self):
        assert _document_ids_from_chunks([]) == []


class TestMergeUnique:
    def test_preserves_first_seen_order_across_sources(self):
        out = _merge_unique(["A", "B"], ["C", "A"], ["B", "D"])
        assert out == ["A", "B", "C", "D"]

    def test_dedupes_case_insensitively(self):
        out = _merge_unique(["Qdrant"], ["QDRANT", "qdrant"])
        assert out == ["Qdrant"]


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
async def test_expand_returns_empty_when_no_names_match_and_no_doc_scope():
    """No substring matches AND no doc-scoped entities for the cited docs."""
    with (
        patch(
            "app.rag.graph_expansion.list_user_entities",
            new=AsyncMock(return_value=[{"name": "OnlyInGraph", "type": "Concept"}]),
        ),
        patch(
            "app.rag.graph_expansion.list_entity_names_for_documents",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await expand_with_graph(
            query="nothing relevant",
            chunks=[_chunk("zero overlap")],
            user_id=uuid4(),
        )

    assert result == []


@pytest.mark.asyncio
async def test_expand_uses_doc_scope_when_query_has_no_name_match():
    """The killer case: question doesn't mention any entity by name, but the
    retrieved chunk comes from a doc whose entities are in the graph."""
    candidates = [{"name": "Qdrant", "type": "Technology"}]
    fact_rows = [
        {
            "name": "Qdrant",
            "type": "Technology",
            "description": "vector DB",
            "relations": [],
        },
    ]
    with (
        patch(
            "app.rag.graph_expansion.list_user_entities",
            new=AsyncMock(return_value=candidates),
        ),
        patch(
            "app.rag.graph_expansion.list_entity_names_for_documents",
            new=AsyncMock(return_value=["Qdrant"]),
        ) as doc_call,
        patch(
            "app.rag.graph_expansion.get_entity_facts",
            new=AsyncMock(return_value=fact_rows),
        ) as facts_call,
    ):
        result = await expand_with_graph(
            query="Summarize what you know",
            chunks=[_chunk("the database stores embeddings", document_id="doc-1")],
            user_id=uuid4(),
        )

    assert len(result) == 1
    assert result[0].name == "Qdrant"
    doc_call.assert_called_once()
    # The cypher fact lookup must have been called with the union of names.
    assert "Qdrant" in facts_call.call_args.args[1]


@pytest.mark.asyncio
async def test_expand_unions_name_match_and_doc_scope_with_name_priority():
    candidates = [
        {"name": "Qdrant", "type": "Technology"},
        {"name": "Cosine Distance", "type": "Concept"},
        {"name": "RapidOCR", "type": "Technology"},
    ]
    # `Qdrant` name-matches; doc-scope returns three (one overlapping, two new).
    fact_rows = [
        {"name": n, "type": "Technology", "description": "", "relations": []}
        for n in ("Qdrant", "Cosine Distance", "RapidOCR")
    ]

    with (
        patch(
            "app.rag.graph_expansion.list_user_entities",
            new=AsyncMock(return_value=candidates),
        ),
        patch(
            "app.rag.graph_expansion.list_entity_names_for_documents",
            new=AsyncMock(return_value=["Qdrant", "Cosine Distance", "RapidOCR"]),
        ),
        patch(
            "app.rag.graph_expansion.get_entity_facts",
            new=AsyncMock(return_value=fact_rows),
        ),
    ):
        result = await expand_with_graph(
            query="What does Qdrant do?",
            chunks=[_chunk("vector DB", document_id="doc-1")],
            user_id=uuid4(),
        )

    names = [f.name for f in result]
    # Qdrant is name-matched → must appear first (priority).
    assert names[0] == "Qdrant"
    # No dupes.
    assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_expand_caps_total_entities():
    candidates = [{"name": f"E{i}", "type": "Concept"} for i in range(50)]
    fact_rows = [
        {"name": f"E{i}", "type": "Concept", "description": "", "relations": []} for i in range(50)
    ]
    with (
        patch(
            "app.rag.graph_expansion.list_user_entities",
            new=AsyncMock(return_value=candidates),
        ),
        patch(
            "app.rag.graph_expansion.list_entity_names_for_documents",
            new=AsyncMock(return_value=[f"E{i}" for i in range(50)]),
        ),
        patch(
            "app.rag.graph_expansion.get_entity_facts",
            new=AsyncMock(return_value=fact_rows),
        ) as facts_call,
    ):
        result = await expand_with_graph(
            query="ignored",
            chunks=[_chunk("ignored too", document_id="doc-1")],
            user_id=uuid4(),
            max_entities=4,
        )

    assert len(result) == 4
    # The cypher lookup was only asked for the cap (not all 50)
    assert len(facts_call.call_args.args[1]) == 4


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
            "app.rag.graph_expansion.list_entity_names_for_documents",
            new=AsyncMock(return_value=[]),
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
            "app.rag.graph_expansion.list_entity_names_for_documents",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.rag.graph_expansion.get_entity_facts",
            new=AsyncMock(return_value=fact_rows),
        ),
    ):
        result = await expand_with_graph(
            query="qdrant",
            chunks=[_chunk("qdrant uses cosine distance")],
            user_id=uuid4(),
        )

    assert len(result[0].relations) == 1
    assert result[0].relations[0].other == "Cosine Distance"
