"""Unit tests for L3 semantic entity alignment (#43c, #43d two-tier)."""

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


# Convenience — mirrors the current production defaults for tests that don't
# specifically care about the tier split.
SAME = 0.85
CROSS = 0.92


class TestFindSemanticAlias:
    def test_returns_none_when_no_candidates(self):
        assert find_semantic_alias(list(_v(1.0, 0.0)), "Concept", [], SAME, CROSS) is None

    def test_returns_match_above_same_type_threshold(self):
        # Near-identical vectors → cosine ≈ 1, same type → same-tier threshold.
        cand = SemanticCandidate(
            name_lower="supervised fine-tuning",
            type="Concept",
            embedding=_v(0.9, 0.1),
        )
        query = list(_v(0.95, 0.08))
        assert (
            find_semantic_alias(query, "Concept", [cand], SAME, CROSS) == "supervised fine-tuning"
        )

    def test_returns_none_below_both_thresholds(self):
        cand = SemanticCandidate(
            name_lower="something else",
            type="Concept",
            embedding=_v(0.0, 1.0),
        )
        # Orthogonal vectors → cosine 0, well below anything.
        assert find_semantic_alias(list(_v(1.0, 0.0)), "Concept", [cand], SAME, CROSS) is None

    def test_picks_highest_scoring_of_multiple_same_type(self):
        query = _v(1.0, 0.0, 0.0)
        cands = [
            SemanticCandidate("far", "Concept", _v(0.0, 1.0, 0.0)),
            SemanticCandidate("near", "Concept", _v(0.99, 0.05, 0.02)),
            SemanticCandidate("mid", "Concept", _v(0.7, 0.7, 0.0)),
        ]
        assert find_semantic_alias(list(query), "Concept", cands, SAME, CROSS) == "near"

    def test_ignores_candidates_with_empty_embedding(self):
        query = _v(1.0, 0.0)
        cands = [
            SemanticCandidate("no-vec", "Concept", ()),
            SemanticCandidate("has-vec", "Concept", _v(0.99, 0.01)),
        ]
        assert find_semantic_alias(list(query), "Concept", cands, SAME, CROSS) == "has-vec"

    def test_ignores_candidates_with_dim_mismatch(self):
        # Corrupted/partial vector from a bad backfill — must not crash.
        query = _v(1.0, 0.0, 0.0)
        cands = [
            SemanticCandidate("short", "Concept", (0.9,)),  # 1-d, dim mismatch
            SemanticCandidate("good", "Concept", _v(0.99, 0.01, 0.02)),
        ]
        assert find_semantic_alias(list(query), "Concept", cands, SAME, CROSS) == "good"

    def test_empty_query_returns_none(self):
        cand = SemanticCandidate("x", "Concept", _v(1.0, 0.0))
        assert find_semantic_alias([], "Concept", [cand], SAME, CROSS) is None

    def test_same_type_threshold_is_inclusive(self):
        """Score == same-type threshold should still alias — matches the >=
        boundary used for L2 fuzzy in alignment.py."""
        # dot product exactly 0.85 by construction, same type.
        query = (0.85, (1 - 0.85**2) ** 0.5)
        cand_emb = (1.0, 0.0)
        cand = SemanticCandidate("edge", "Concept", cand_emb)
        assert find_semantic_alias(list(query), "Concept", [cand], SAME, CROSS) == "edge"


class TestTwoTierThreshold:
    """#43d: cross-type matches are allowed but at a stricter threshold so
    the extractor's inconsistent typing (SFT typed Technology, Supervised
    Fine-Tuning typed Concept for the same real concept) doesn't leave the
    KG with duplicate hubs."""

    def test_cross_type_match_above_cross_threshold_aliases(self):
        """SFT (Technology) sees Supervised Fine-Tuning (Concept) with very
        high semantic similarity → alias despite different types."""
        # Same vector, different type. Should alias at cross threshold.
        cand = SemanticCandidate(
            name_lower="supervised fine-tuning",
            type="Concept",
            embedding=_v(1.0, 0.0),
        )
        query = list(_v(1.0, 0.0))  # cosine = 1.0, clears 0.92
        assert (
            find_semantic_alias(query, "Technology", [cand], SAME, CROSS)
            == "supervised fine-tuning"
        )

    def test_cross_type_below_cross_threshold_does_not_alias(self):
        """Java Location vs Java Technology — same string, different real
        concept. Cosine 0.88 is above the same-type threshold (0.85) but
        below the strict cross-type threshold (0.92), so cross-type stays
        separate — exactly the failure mode #43d guards against."""
        # Build a query where dot(query, cand) = 0.88 exactly.
        # cand = (1, 0), query = (0.88, sqrt(1 - 0.88**2)) → dot = 0.88.
        cand = SemanticCandidate(name_lower="java", type="Location", embedding=(1.0, 0.0))
        query = [0.88, (1 - 0.88**2) ** 0.5]
        # Different type → uses cross threshold (0.92). 0.88 < 0.92 → no alias.
        assert find_semantic_alias(query, "Technology", [cand], SAME, CROSS) is None

    def test_same_type_wins_ties_over_cross_type(self):
        """When both a same-type and a cross-type candidate clear their
        thresholds, prefer the same-type match — it's the safer merge."""
        same_type = SemanticCandidate(
            name_lower="same-type-match",
            type="Concept",
            embedding=_v(0.9, 0.1),  # cosine with query ≈ 0.94
        )
        cross_type = SemanticCandidate(
            name_lower="cross-type-match",
            type="Technology",
            embedding=_v(1.0, 0.0),  # cosine with query ≈ 0.99 (higher!)
        )
        query = list(_v(0.98, 0.19))
        # cross-type has higher raw score, but same-type wins by policy.
        assert (
            find_semantic_alias(query, "Concept", [same_type, cross_type], SAME, CROSS)
            == "same-type-match"
        )

    def test_cross_type_used_only_when_no_same_type_match(self):
        """Same-type candidate exists but doesn't clear its threshold; a
        cross-type candidate clears the stricter cross threshold. Return the
        cross-type."""
        weak_same = SemanticCandidate(
            name_lower="weak-same-type",
            type="Concept",
            embedding=_v(0.0, 1.0),  # cosine 0 with query → far below 0.85
        )
        strong_cross = SemanticCandidate(
            name_lower="strong-cross-type",
            type="Technology",
            embedding=_v(1.0, 0.0),  # cosine 1.0 with query → clears 0.92
        )
        query = list(_v(1.0, 0.0))
        assert (
            find_semantic_alias(query, "Concept", [weak_same, strong_cross], SAME, CROSS)
            == "strong-cross-type"
        )

    def test_cross_type_threshold_is_inclusive(self):
        """Score == cross_type_threshold should alias — >= boundary."""
        # dot product exactly 0.92 by construction, cross type.
        query = (0.92, (1 - 0.92**2) ** 0.5)
        cand = SemanticCandidate("edge-cross", "Concept", (1.0, 0.0))
        assert find_semantic_alias(list(query), "Technology", [cand], SAME, CROSS) == "edge-cross"
