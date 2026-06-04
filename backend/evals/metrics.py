"""Pure scoring functions for the eval suite — no I/O, easy to unit-test."""

from __future__ import annotations

from collections.abc import Iterable


def recall_at_k(expected: Iterable[str], retrieved: Iterable[str]) -> float:
    """Fraction of `expected` ids present in `retrieved` (already top-K).
    Empty `expected` returns 1.0 so ungrounded questions don't tank the avg.
    """
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    retrieved_set = set(retrieved)
    return len(expected_set & retrieved_set) / len(expected_set)


def keyword_coverage(expected_keywords: Iterable[str], answer: str) -> float:
    """Fraction of keywords present in `answer` (case-insensitive substring).
    Substring match tolerates plurals/inflection without an NLP dep.
    """
    keywords = [kw for kw in expected_keywords if kw]
    if not keywords:
        return 1.0
    ans = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in ans)
    return hits / len(keywords)


def mean(values: Iterable[float]) -> float | None:
    """Arithmetic mean, or None if the sequence is empty."""
    vs = list(values)
    if not vs:
        return None
    return sum(vs) / len(vs)
