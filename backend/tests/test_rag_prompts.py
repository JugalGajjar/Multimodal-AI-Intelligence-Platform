"""Unit tests for the RAG prompt assembly."""

from app.rag.prompts import (
    NO_CONTEXT_FALLBACK_SYSTEM,
    SYSTEM_PROMPT,
    build_context_block,
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


class TestBuildContextBlock:
    def test_numbers_chunks_starting_at_1(self):
        out = build_context_block([_chunk(0, "alpha"), _chunk(1, "beta")])

        assert "[1]" in out
        assert "[2]" in out
        assert "alpha" in out
        assert "beta" in out

    def test_empty_chunks_returns_empty_string(self):
        assert build_context_block([]) == ""

    def test_includes_score_and_indexes(self):
        out = build_context_block([_chunk(7, "hello", score=0.84)])

        assert "chunk=7" in out
        assert "0.840" in out


class TestBuildUserMessage:
    def test_with_chunks_includes_context_and_question(self):
        msg = build_user_message(
            "What is X?",
            [_chunk(0, "X is defined as foo.")],
        )

        assert "Context passages:" in msg
        assert "[1]" in msg
        assert "X is defined as foo." in msg
        assert "Question: What is X?" in msg

    def test_without_chunks_returns_raw_query(self):
        msg = build_user_message("just a question", [])

        assert msg == "just a question"


class TestSystemPrompts:
    def test_main_prompt_mentions_inline_citations(self):
        assert "[N]" in SYSTEM_PROMPT or "[" in SYSTEM_PROMPT
        assert "context" in SYSTEM_PROMPT.lower()

    def test_no_context_prompt_steers_user_to_upload(self):
        assert "upload" in NO_CONTEXT_FALLBACK_SYSTEM.lower()
