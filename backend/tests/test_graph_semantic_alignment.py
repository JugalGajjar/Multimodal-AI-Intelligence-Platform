"""Unit tests for L3 semantic entity alignment (#43c)."""

from app.graph.semantic_alignment import (
    SemanticCandidate,
    find_semantic_alias,
    format_entity_text,
)


class TestFormatEntityText:
    def test_name_plus_description(self):
        assert format_entity_text("SFT", "supervised fine-tuning method") == (
            "SFT: supervised fine-tuning method"
        )

    def test_falls_back_to_bare_name_without_description(self):
        assert format_entity_text("RSAT") == "RSAT"
        assert format_entity_text("RSAT", "") == "RSAT"

    def test_strips_surrounding_whitespace(self):
        assert format_entity_text("  Alice  ", "  researcher  ") == "Alice: researcher"

    def test_empty_name_yields_empty_string(self):
        assert format_entity_text("", "desc") == ": desc"  # explicit — caller filters


def _v(*parts: float) -> tuple[float, ...]:
    """L2-normalize a small vector so the dot product acts like cosine sim."""
    total = sum(p * p for p in parts) ** 0.5 or 1.0
    return tuple(p / total for p in parts)


class TestFindSemanticAlias:
    def test_returns_none_when_no_candidates(self):
        assert find_semantic_alias(list(_v(1.0, 0.0)), "Concept", [], 0.85) is None

    def test_returns_none_when_type_mismatch(self):
        # Identical vector but different type — must NOT alias across types.
        emb = _v(1.0, 0.0)
        cand = SemanticCandidate(name_lower="x", type="Person", embedding=emb)
        assert find_semantic_alias(list(emb), "Concept", [cand], 0.85) is None

    def test_returns_match_above_threshold(self):
        # Near-identical vectors → cosine ≈ 1.
        cand = SemanticCandidate(
            name_lower="supervised fine-tuning",
            type="Concept",
            embedding=_v(0.9, 0.1),
        )
        # Slightly rotated but still very similar.
        query = list(_v(0.95, 0.08))
        assert find_semantic_alias(query, "Concept", [cand], 0.85) == "supervised fine-tuning"

    def test_returns_none_below_threshold(self):
        cand = SemanticCandidate(
            name_lower="something else",
            type="Concept",
            embedding=_v(0.0, 1.0),
        )
        # Orthogonal vectors → cosine 0.
        assert find_semantic_alias(list(_v(1.0, 0.0)), "Concept", [cand], 0.85) is None

    def test_picks_highest_scoring_of_multiple_same_type(self):
        query = _v(1.0, 0.0, 0.0)
        cands = [
            SemanticCandidate("far", "Concept", _v(0.0, 1.0, 0.0)),
            SemanticCandidate("near", "Concept", _v(0.99, 0.05, 0.02)),
            SemanticCandidate("mid", "Concept", _v(0.7, 0.7, 0.0)),
        ]
        assert find_semantic_alias(list(query), "Concept", cands, 0.85) == "near"

    def test_ignores_candidates_with_empty_embedding(self):
        query = _v(1.0, 0.0)
        cands = [
            SemanticCandidate("no-vec", "Concept", ()),
            SemanticCandidate("has-vec", "Concept", _v(0.99, 0.01)),
        ]
        assert find_semantic_alias(list(query), "Concept", cands, 0.85) == "has-vec"

    def test_ignores_candidates_with_dim_mismatch(self):
        # Corrupted/partial vector from a bad backfill — must not crash.
        query = _v(1.0, 0.0, 0.0)
        cands = [
            SemanticCandidate("short", "Concept", (0.9,)),  # 1-d, dim mismatch
            SemanticCandidate("good", "Concept", _v(0.99, 0.01, 0.02)),
        ]
        assert find_semantic_alias(list(query), "Concept", cands, 0.85) == "good"

    def test_empty_query_returns_none(self):
        cand = SemanticCandidate("x", "Concept", _v(1.0, 0.0))
        assert find_semantic_alias([], "Concept", [cand], 0.85) is None

    def test_threshold_is_inclusive(self):
        """Score == threshold should still alias — matches the >= boundary
        used for L2 fuzzy in alignment.py."""
        # dot product exactly 0.85 by construction.
        query = (0.85, (1 - 0.85**2) ** 0.5)
        cand_emb = (1.0, 0.0)
        cand = SemanticCandidate("threshold-edge", "Concept", cand_emb)
        assert find_semantic_alias(list(query), "Concept", [cand], 0.85) == "threshold-edge"
