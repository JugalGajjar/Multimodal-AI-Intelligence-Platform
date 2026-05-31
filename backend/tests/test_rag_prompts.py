"""Unit tests for the RAG prompt assembly (chunks + graph)."""

from app.rag.graph_expansion import GraphFact, GraphRelation
from app.rag.prompts import (
    NO_CONTEXT_FALLBACK_SYSTEM,
    SYSTEM_PROMPT,
    build_context_block,
    build_graph_block,
    build_user_message,
)
from app.rag.retrieval import RetrievedChunk


def _chunk(idx: int, text: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="00000000-0000-0000-0000-000000000000",
        document_id="11111111-1111-1111-1111-111111111111",
        chunk_index=idx,
        score=score,
        text=text,
    )


def _fact(name: str, relations: list[GraphRelation] | None = None) -> GraphFact:
    return GraphFact(
        name=name,
        type="Technology",
        description=f"{name} description",
        relations=relations or [],
    )


class TestBuildContextBlock:
    def test_numbers_chunks_starting_at_1(self):
        out = build_context_block([_chunk(0, "alpha"), _chunk(1, "beta")])

        assert "[1]" in out and "[2]" in out
        assert "alpha" in out and "beta" in out

    def test_empty_chunks_returns_empty_string(self):
        assert build_context_block([]) == ""

    def test_includes_score_and_indexes(self):
        out = build_context_block([_chunk(7, "hello", score=0.84)])

        assert "chunk=7" in out
        assert "0.840" in out


class TestBuildGraphBlock:
    def test_renders_entity_header_and_arrows(self):
        facts = [
            _fact(
                "Qdrant",
                relations=[
                    GraphRelation(
                        relation="uses",
                        direction="out",
                        other="Cosine Distance",
                    ),
                    GraphRelation(
                        relation="is part of",
                        direction="in",
                        other="MMAP Platform",
                    ),
                ],
            )
        ]

        out = build_graph_block(facts)

        assert "Qdrant (Technology)" in out
        assert "→ uses Cosine Distance" in out
        assert "← is part of MMAP Platform" in out

    def test_empty_facts_returns_empty_string(self):
        assert build_graph_block([]) == ""

    def test_renders_multiple_entities(self):
        facts = [_fact("A"), _fact("B")]

        out = build_graph_block(facts)

        assert "A (Technology)" in out
        assert "B (Technology)" in out

    def test_renders_multi_hop_with_chain_arrow_and_hop_tag(self):
        facts = [
            _fact(
                "Bandit",
                relations=[
                    GraphRelation(
                        relation="used by → repairs",
                        other="Vulnerability",
                        distance=2,
                        relation_chain=["used by", "repairs"],
                    )
                ],
            )
        ]

        out = build_graph_block(facts)

        assert "↝ used by → repairs Vulnerability" in out
        assert "(2-hop)" in out

    def test_mixed_1_and_2_hop_facts_render_distinctly(self):
        facts = [
            _fact(
                "Qdrant",
                relations=[
                    GraphRelation(
                        relation="uses",
                        other="Cosine Distance",
                        distance=1,
                        relation_chain=["uses"],
                        direction="out",
                    ),
                    GraphRelation(
                        relation="uses → part of",
                        other="Vector Math",
                        distance=2,
                        relation_chain=["uses", "part of"],
                    ),
                ],
            )
        ]

        out = build_graph_block(facts)

        assert "→ uses Cosine Distance" in out
        assert "↝ uses → part of Vector Math" in out
        assert "(2-hop)" in out


class TestBuildUserMessage:
    def test_with_chunks_only_includes_passages_section(self):
        msg = build_user_message("What is X?", [_chunk(0, "X is defined as foo.")])

        assert "Context passages:" in msg
        assert "Knowledge-graph facts:" not in msg
        assert "X is defined as foo." in msg
        assert "Question: What is X?" in msg

    def test_with_chunks_and_facts_includes_both_sections(self):
        msg = build_user_message(
            query="What uses cosine?",
            chunks=[_chunk(0, "Qdrant is the vector DB")],
            facts=[
                _fact(
                    "Qdrant",
                    relations=[
                        GraphRelation(
                            relation="uses",
                            direction="out",
                            other="Cosine Distance",
                        )
                    ],
                )
            ],
        )

        assert "Context passages:" in msg
        assert "Knowledge-graph facts:" in msg
        assert "Qdrant" in msg
        assert "Cosine Distance" in msg

    def test_with_facts_only_still_works(self):
        msg = build_user_message(
            query="What uses cosine?",
            chunks=[],
            facts=[_fact("Qdrant")],
        )

        assert "Knowledge-graph facts:" in msg
        assert "Qdrant" in msg

    def test_without_chunks_or_facts_returns_raw_query(self):
        assert build_user_message("just a question", []) == "just a question"


class TestSystemPrompts:
    def test_main_prompt_mentions_inline_citations(self):
        assert "[N]" in SYSTEM_PROMPT
        assert "context" in SYSTEM_PROMPT.lower()

    def test_main_prompt_mentions_graph(self):
        assert "graph" in SYSTEM_PROMPT.lower()

    def test_no_context_prompt_steers_user_to_upload(self):
        assert "upload" in NO_CONTEXT_FALLBACK_SYSTEM.lower()
