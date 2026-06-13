"""Pure-helper tests for chat search: snippet windowing + ILIKE escaping."""

from app.chats.router import _escape_like, _snippet
from app.chats.service import placeholder_title


class TestEscapeLike:
    def test_escapes_percent_underscore_backslash(self):
        assert _escape_like("100%_done\\x") == "100\\%\\_done\\\\x"

    def test_plain_text_unchanged(self):
        assert _escape_like("hello world") == "hello world"


class TestSnippet:
    def test_short_text_returned_whole(self):
        assert _snippet("short text", "short") == "short text"

    def test_centers_on_match(self):
        text = "a" * 300 + " needle " + "b" * 300
        out = _snippet(text, "needle")
        assert "needle" in out
        assert out.startswith("…")
        assert out.endswith("…")
        assert len(out) <= 162  # width + ellipses

    def test_match_at_start_has_no_leading_ellipsis(self):
        text = "needle " + "b" * 300
        out = _snippet(text, "needle")
        assert out.startswith("needle")
        assert out.endswith("…")

    def test_no_match_falls_back_to_head(self):
        text = "c" * 300
        out = _snippet(text, "zzz")
        assert out.endswith("…")

    def test_collapses_whitespace(self):
        assert _snippet("a\n\nb\tc", "b") == "a b c"

    def test_case_insensitive_match(self):
        text = "x" * 200 + " NEEDLE " + "y" * 200
        assert "NEEDLE" in _snippet(text, "needle")


class TestPlaceholderTitle:
    def test_short_query_kept_verbatim(self):
        assert placeholder_title("What is RAG?") == "What is RAG?"

    def test_long_query_trims_at_word_boundary(self):
        q = "tell me everything about retrieval augmented generation pipelines please"
        out = placeholder_title(q)
        assert len(out) <= 61
        assert out.endswith("…")
        assert " retrieval" in out or out.startswith("tell me")

    def test_empty_query_falls_back(self):
        assert placeholder_title("   ") == "New chat"

    def test_whitespace_collapsed(self):
        assert placeholder_title("a   b\n\nc") == "a b c"
