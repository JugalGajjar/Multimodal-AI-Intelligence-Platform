"""Query-centered text snippet helper.

Used by citation previews (rag/router) and chat search results (chats/router)
so the user sees the matched part of a chunk instead of its arbitrary head.
"""

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "by",
        "with",
        "as",
        "it",
        "its",
        "this",
        "that",
        "what",
        "which",
        "who",
        "how",
        "why",
        "when",
        "where",
        "do",
        "does",
        "did",
        "i",
        "you",
        "we",
        "they",
        "he",
        "she",
    }
)


def _best_match(text_lower: str, query_tokens: list[str]) -> tuple[int, int]:
    """Return (offset, token_length) of the first matching query token.
    Falls back to (-1, 0) when nothing matches."""
    for tok in query_tokens:
        idx = text_lower.find(tok)
        if idx >= 0:
            return idx, len(tok)
    return -1, 0


def snippet(text: str, query: str, *, width: int = 280) -> str:
    """Window of ``width`` chars centered on the first query-token match.

    - Collapses whitespace so previews are single-line.
    - Skips short stopwords when picking what to center on.
    - Falls back to the head of the text if no token matches.
    """
    text = " ".join(text.split())
    if len(text) <= width:
        return text

    tokens = [t for t in (w.lower().strip(".,;:!?\"'()[]") for w in query.split()) if t]
    meaningful = [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]
    candidates = meaningful or tokens

    idx, tok_len = _best_match(text.lower(), candidates)
    if idx < 0:
        return text[:width].rstrip() + "…"

    start = max(0, idx + tok_len // 2 - width // 2)
    end = min(len(text), start + width)
    start = max(0, end - width)
    out = text[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out
