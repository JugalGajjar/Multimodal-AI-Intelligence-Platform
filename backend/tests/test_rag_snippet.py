"""Query-centered snippet helper used by citation previews + chat search."""

from app.rag.snippet import snippet


class TestSnippet:
    def test_short_text_returned_whole(self):
        assert snippet("short text", "short") == "short text"

    def test_centers_on_first_token_match(self):
        text = "a" * 300 + " needle " + "b" * 300
        out = snippet(text, "find the needle", width=160)
        assert "needle" in out
        assert out.startswith("…")
        assert out.endswith("…")
        assert len(out) <= 162

    def test_match_at_start_has_no_leading_ellipsis(self):
        text = "needle " + "b" * 300
        out = snippet(text, "needle", width=160)
        assert out.startswith("needle")
        assert out.endswith("…")

    def test_no_match_falls_back_to_head(self):
        text = "c" * 300
        out = snippet(text, "zzz nothing here", width=160)
        assert out.endswith("…")

    def test_collapses_whitespace(self):
        assert snippet("a\n\nb\tc", "b") == "a b c"

    def test_case_insensitive_match(self):
        text = "x" * 200 + " NEEDLE " + "y" * 200
        assert "NEEDLE" in snippet(text, "needle", width=160)

    def test_skips_stopwords_when_choosing_token(self):
        # The token "the" would otherwise win first match position; the
        # helper should center on "needle" because stopwords are skipped.
        text = "the " + "x" * 240 + " needle " + "y" * 240
        out = snippet(text, "what is the needle", width=160)
        assert "needle" in out

    def test_strips_query_punctuation(self):
        # Trailing punctuation in the query shouldn't break the match.
        text = "x" * 200 + " kubernetes " + "y" * 200
        assert "kubernetes" in snippet(text, "kubernetes?", width=160)
