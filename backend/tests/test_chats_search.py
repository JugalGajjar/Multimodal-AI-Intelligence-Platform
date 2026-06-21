"""Pure-helper tests for chat search: ILIKE escaping + placeholder titles.

The snippet helper is shared with citation previews and lives in
test_rag_snippet.py.
"""

from app.chats.router import _escape_like
from app.chats.service import placeholder_title


class TestEscapeLike:
    def test_escapes_percent_underscore_backslash(self):
        assert _escape_like("100%_done\\x") == "100\\%\\_done\\\\x"

    def test_plain_text_unchanged(self):
        assert _escape_like("hello world") == "hello world"


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
