"""Per-document diversification in the retrieval pipeline.

The reranker gives us a score-ordered list. `_diversify` enforces a
max-chunks-per-document cap so a single verbose doc can't monopolise
every citation slot — but backfills from overflow when the strict cap
would leave us below `top_k`.
"""

from app.rag.retrieval import RetrievedChunk, _diversify


def _chunk(doc_id: str, chunk_index: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"{doc_id}-{chunk_index}",
        document_id=doc_id,
        chunk_index=chunk_index,
        score=score,
        text=f"chunk {doc_id}#{chunk_index}",
    )


class TestDiversify:
    def test_returns_top_k_untouched_when_pool_is_smaller(self):
        pool = [_chunk("A", 0, 0.9), _chunk("A", 1, 0.8)]
        assert _diversify(pool, top_k=5, max_per_doc=2) == pool

    def test_zero_cap_disables_diversification(self):
        pool = [_chunk("A", i, 1.0 - i * 0.1) for i in range(5)]
        # max_per_doc=0 → treat as disabled, keep score order.
        assert _diversify(pool, top_k=3, max_per_doc=0) == pool[:3]

    def test_caps_at_two_per_doc_when_mixed_pool_is_available(self):
        pool = [
            _chunk("A", 0, 0.90),
            _chunk("A", 1, 0.85),
            _chunk("A", 2, 0.80),  # would be 3rd from A → capped, moved to overflow
            _chunk("B", 0, 0.70),
            _chunk("A", 3, 0.65),  # would be 3rd from A → capped
            _chunk("B", 1, 0.60),
            _chunk("C", 0, 0.50),
        ]
        out = _diversify(pool, top_k=5, max_per_doc=2)
        # Distinct doc coverage: A×2, B×2, C×1 = 3 distinct docs across 5 slots.
        by_doc = {c.document_id for c in out}
        assert by_doc == {"A", "B", "C"}
        # A shows up exactly twice, B twice, C once.
        counts = {"A": 0, "B": 0, "C": 0}
        for c in out:
            counts[c.document_id] += 1
        assert counts == {"A": 2, "B": 2, "C": 1}

    def test_preserves_score_order_within_the_cap(self):
        pool = [
            _chunk("A", 0, 0.9),
            _chunk("A", 1, 0.85),
            _chunk("B", 0, 0.7),
        ]
        out = _diversify(pool, top_k=3, max_per_doc=2)
        assert [c.score for c in out] == [0.9, 0.85, 0.7]

    def test_backfills_from_overflow_when_only_one_doc_qualifies(self):
        """A single-source query (only one document is relevant) should still
        return top_k results — otherwise the user sees 2 chunks when they
        asked for 5, which is worse UX than the diversification is worth."""
        pool = [_chunk("A", i, 1.0 - i * 0.05) for i in range(5)]
        out = _diversify(pool, top_k=4, max_per_doc=2)
        # All 4 slots filled, all from A (backfill kicked in).
        assert len(out) == 4
        assert all(c.document_id == "A" for c in out)
        # And in score order.
        scores = [c.score for c in out]
        assert scores == sorted(scores, reverse=True)

    def test_stops_at_top_k_even_when_more_would_qualify(self):
        pool = [
            _chunk("A", 0, 0.9),
            _chunk("B", 0, 0.8),
            _chunk("C", 0, 0.7),
            _chunk("D", 0, 0.6),
        ]
        out = _diversify(pool, top_k=2, max_per_doc=2)
        assert len(out) == 2
        assert [c.document_id for c in out] == ["A", "B"]

    def test_empty_pool_returns_empty(self):
        assert _diversify([], top_k=5, max_per_doc=2) == []
