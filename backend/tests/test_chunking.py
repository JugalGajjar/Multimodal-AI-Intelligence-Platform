"""Unit tests for the recursive character chunker."""

import pytest

from app.workers.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_text,
)


class TestEdges:
    def test_empty_text_returns_empty_list(self):
        assert chunk_text("") == []

    def test_text_shorter_than_chunk_size_yields_single_chunk(self):
        chunks = chunk_text("short", chunk_size=100)

        assert len(chunks) == 1
        assert chunks[0].text == "short"
        assert chunks[0].char_start == 0
        assert chunks[0].char_end == 5
        assert chunks[0].index == 0

    def test_invalid_args_raise(self):
        with pytest.raises(ValueError):
            chunk_text("x", chunk_size=0)
        with pytest.raises(ValueError):
            chunk_text("x", chunk_size=10, chunk_overlap=10)
        with pytest.raises(ValueError):
            chunk_text("x", chunk_size=10, chunk_overlap=15)


class TestSplitting:
    def test_long_text_produces_multiple_chunks(self):
        # 2000 chars at default 500-size → roughly 4-5 chunks with overlap
        text = "abcdefghij" * 200
        chunks = chunk_text(text)

        assert len(chunks) >= 4
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(text)

    def test_offsets_index_into_original_text(self):
        text = "abcdefghij" * 200
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)

        for c in chunks:
            assert text[c.char_start : c.char_end] == c.text

    def test_chunks_overlap_by_overlap_amount(self):
        # Use plain alphabet so no natural break interferes
        text = "abcdefghij" * 30  # 300 chars
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)

        # Consecutive chunks should share `chunk_overlap` characters
        for prev, curr in zip(chunks, chunks[1:], strict=False):
            tail = prev.text[-20:]
            head = curr.text[:20]
            assert tail == head

    def test_indexes_are_sequential(self):
        text = "x" * 1500
        chunks = chunk_text(text, chunk_size=300, chunk_overlap=30)

        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_prefers_paragraph_break_over_mid_word(self):
        para_a = "a" * 480
        para_b = "b" * 480
        text = f"{para_a}\n\n{para_b}"
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=20)

        # First chunk should end right after the paragraph break, not mid-`b`
        first = chunks[0]
        assert first.text.endswith("\n\n") or first.text.endswith("\n")

    def test_each_chunk_within_size_bound(self):
        text = "lorem ipsum dolor sit amet " * 200
        size = 200
        chunks = chunk_text(text, chunk_size=size, chunk_overlap=20)

        for c in chunks:
            assert len(c.text) <= size

    def test_defaults_are_sensible(self):
        assert DEFAULT_CHUNK_SIZE == 500
        assert DEFAULT_CHUNK_OVERLAP == 50
        assert DEFAULT_CHUNK_OVERLAP < DEFAULT_CHUNK_SIZE


class TestIsMeaningful:
    def test_rejects_tiny_fragments(self):
        from app.workers.chunking import MIN_MEANINGFUL_ALNUM_CHARS, is_meaningful

        # The actual noise from the bug report.
        assert not is_meaningful("rs")
        assert not is_meaningful("rsal).")
        assert not is_meaningful("rmat [1")
        # Just under the bar.
        assert not is_meaningful("a" * (MIN_MEANINGFUL_ALNUM_CHARS - 1))

    def test_accepts_real_prose(self):
        from app.workers.chunking import is_meaningful

        text = (
            "RSAT trains small language models to produce step-by-step reasoning "
            "over tables where each step cites the cells it depends on."
        )
        assert is_meaningful(text)

    def test_punctuation_doesnt_count_toward_min(self):
        from app.workers.chunking import MIN_MEANINGFUL_ALNUM_CHARS, is_meaningful

        # All punctuation, no alphanumerics — would pass a naive len() check
        # but not a content check.
        assert not is_meaningful("." * (MIN_MEANINGFUL_ALNUM_CHARS * 3))
