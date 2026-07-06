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


class TestSectionAwareChunking:
    """The section-aware chunker prepends the enclosing heading to each chunk
    so retrieval sees "PUBLICATIONS\\nRSAT: ..." rather than an orphan bullet."""

    def test_all_caps_heading_prefixed_to_each_chunk(self):
        text = (
            "RESEARCH PUBLICATIONS\n"
            "RSAT: Structured Attribution Makes Small Language Models "
            "Faithful Table Reasoners. First author. SURGeLLM Workshop at "
            "ACL 2026, July 2026.\n"
            "Feature Attribution Stability Suite. Co-author. XAI4CV "
            "Workshop at CVPR 2026, June 2026.\n"
        )
        chunks = chunk_text(text)
        assert chunks
        for c in chunks:
            assert c.text.startswith("RESEARCH PUBLICATIONS\n")

    def test_markdown_heading_recognized(self):
        text = "## Overview\nThe system indexes chunks into Qdrant."
        chunks = chunk_text(text)
        assert chunks and all(c.text.startswith("## Overview\n") for c in chunks)

    def test_page_marker_from_pdf_treated_as_section_boundary(self):
        text = (
            "--- page 1 ---\n"
            "Introduction paragraph on page one with meaningful content "
            "long enough to survive chunking.\n"
            "--- page 2 ---\n"
            "Second page content that should be its own section with its "
            "own page marker prepended.\n"
        )
        chunks = chunk_text(text)
        page1 = [c for c in chunks if c.text.startswith("--- page 1 ---")]
        page2 = [c for c in chunks if c.text.startswith("--- page 2 ---")]
        assert page1 and page2

    def test_pptx_slide_marker_treated_as_section_boundary(self):
        text = (
            "--- slide 1 ---\n"
            "Body content of slide one, long enough to matter for chunking.\n"
            "--- slide 2 ---\n"
            "Body content of slide two, also long enough to be indexed.\n"
        )
        chunks = chunk_text(text)
        assert any(c.text.startswith("--- slide 1 ---") for c in chunks)
        assert any(c.text.startswith("--- slide 2 ---") for c in chunks)

    def test_numbered_section_heading_recognized(self):
        text = (
            "1. Introduction\n"
            "This is the introduction of a paper that talks at length "
            "about the motivation behind the work.\n"
            "2. Related Work\n"
            "This section surveys prior work in the field.\n"
        )
        chunks = chunk_text(text)
        assert any(c.text.startswith("1. Introduction\n") for c in chunks)
        assert any(c.text.startswith("2. Related Work\n") for c in chunks)

    def test_text_without_any_heading_still_chunks(self):
        text = (
            "This is a plain paragraph without any heading structure at "
            "all — the chunker must fall back to the character-based "
            "splitter and still produce chunks like it did before the "
            "section-aware upgrade landed. " * 3
        )
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=20)
        assert len(chunks) >= 2
        # No spurious heading prefix on unstructured text.
        for c in chunks:
            assert not c.text.startswith("--- ")

    def test_long_section_still_gets_subsplit(self):
        # A section whose body is much bigger than chunk_size should split
        # into multiple chunks — each carrying the heading prefix.
        body = "Word " * 400  # ≈ 2000 chars
        text = "PUBLICATIONS\n" + body
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) >= 4
        for c in chunks:
            assert c.text.startswith("PUBLICATIONS\n")

    def test_short_all_caps_not_matched(self):
        # "OK." shouldn't be treated as a heading — bare 2-letter caps have
        # too many false positives (initials, abbreviations mid-sentence).
        from app.workers.chunking import _is_heading

        assert not _is_heading("OK.")
        assert not _is_heading("A")

    def test_char_offsets_still_point_into_original_text(self):
        text = (
            "INTRODUCTION\n"
            "This is the intro paragraph with enough words in it to make "
            "the chunker actually produce a chunk we can measure.\n"
        )
        chunks = chunk_text(text)
        for c in chunks:
            # Character offsets should point at body text; the heading prefix
            # is metadata prepended to the chunk `text`, not indexed via
            # char_start/char_end.
            body_slice = text[c.char_start : c.char_end]
            assert "This is the intro" in body_slice or "chunker" in body_slice
