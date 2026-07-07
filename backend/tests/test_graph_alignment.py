"""Unit tests for the entity/relation alignment layer (#43a)."""

from app.graph.alignment import (
    FUZZY_THRESHOLD,
    RELATION_ALIASES,
    AlignedEntity,
    AlignedRelationship,
    Candidate,
    align_batch,
    find_alias,
    normalize_name,
    normalize_relation,
)
from app.graph.schema import GraphEntity, GraphRelationship


class TestNormalizeName:
    def test_lowercases_and_strips(self):
        assert normalize_name("  Jugal Gajjar  ") == "jugal gajjar"

    def test_drops_trailing_punctuation(self):
        assert normalize_name("GWU.") == "gwu"
        assert normalize_name("MIT,") == "mit"
        assert normalize_name("Stanford;") == "stanford"

    def test_collapses_internal_whitespace(self):
        assert normalize_name("George   Washington    University") == "george washington university"

    def test_drops_leading_articles(self):
        assert normalize_name("The MIT") == "mit"
        assert normalize_name("A hospital") == "hospital"
        assert normalize_name("An organization") == "organization"

    def test_only_strips_leading_article_once(self):
        # "the the office" → "the office" (only one strip, not both)
        assert normalize_name("The The Office") == "the office"

    def test_nfkc_folds_fullwidth(self):
        # Fullwidth Latin capitals fold to ASCII
        assert normalize_name("ＭＩＴ") == "mit"

    def test_empty_and_whitespace_return_empty(self):
        assert normalize_name("") == ""
        assert normalize_name("   ") == ""

    def test_preserves_internal_dashes_and_slashes(self):
        # "gpt-oss-120b" is a canonical identifier — must not lose the dashes.
        assert normalize_name("gpt-oss-120b") == "gpt-oss-120b"
        assert normalize_name("BAAI/bge-small-en-v1.5") == "baai/bge-small-en-v1.5"


class TestFindAlias:
    def _cands(self, *pairs: tuple[str, str]) -> list[Candidate]:
        return [Candidate(name_lower=n, type=t) for n, t in pairs]

    def test_exact_match_short_circuits(self):
        cands = self._cands(("jugal gajjar", "Person"), ("qdrant", "Technology"))
        assert find_alias("jugal gajjar", "Person", cands) == "jugal gajjar"

    def test_returns_none_when_no_candidates(self):
        assert find_alias("anything", "Person", []) is None

    def test_returns_none_when_type_never_matches(self):
        cands = self._cands(("qdrant", "Technology"))
        assert find_alias("qdrant", "Person", cands) is None

    def test_catches_single_char_typo(self):
        # "Kamalasankaris" vs "Kamalasankari" — 1 char off, ~96 similarity.
        cands = self._cands(("kamalasankari subramaniakuppusamy", "Person"))
        assert (
            find_alias("kamalasankaris subramaniakuppusamy", "Person", cands)
            == "kamalasankari subramaniakuppusamy"
        )

    def test_ignores_below_threshold(self):
        # Substantially different names, same type — should NOT alias.
        cands = self._cands(("java", "Technology"))
        assert find_alias("javascript", "Technology", cands) is None

    def test_token_sort_ratio_catches_reorder(self):
        # "John Smith" vs "Smith John" — token order doesn't matter.
        cands = self._cands(("smith john", "Person"))
        assert find_alias("john smith", "Person", cands) == "smith john"

    def test_type_scoping_prevents_cross_type_collisions(self):
        # Two identical strings, different types → no alias.
        cands = self._cands(("apple", "Organization"))
        assert find_alias("apple", "Concept", cands) is None

    def test_threshold_is_the_documented_value(self):
        # If someone lowers FUZZY_THRESHOLD accidentally we want to catch it.
        assert FUZZY_THRESHOLD == 90


class TestNormalizeRelation:
    def test_maps_authorship_variants_to_authored(self):
        for phrase in ("author of", "authors", "wrote", "writes"):
            assert normalize_relation(phrase) == "authored"

    def test_maps_affiliation_variants(self):
        for phrase in ("works at", "works for", "employed by", "member of"):
            assert normalize_relation(phrase) == "affiliated with"

    def test_maps_usage_variants(self):
        for phrase in ("using", "utilizes", "leverages"):
            assert normalize_relation(phrase) == "uses"

    def test_maps_comparison_variants(self):
        for phrase in ("better than", "exceeds", "surpasses"):
            assert normalize_relation(phrase) == "outperforms"

    def test_case_and_whitespace_insensitive(self):
        assert normalize_relation("  Works  At ") == "affiliated with"

    def test_unknown_predicate_passes_through_normalized(self):
        assert normalize_relation("Foo Bar Baz") == "foo bar baz"

    def test_empty_returns_empty(self):
        assert normalize_relation("") == ""
        assert normalize_relation("   ") == ""

    def test_alias_table_values_are_lowercase(self):
        # Canonical forms must be lowercase — otherwise MERGE keys mismatch.
        for canonical in RELATION_ALIASES.values():
            assert canonical == canonical.lower()


class TestAlignBatch:
    """Integration-ish tests for the batch aligner — the entrypoint the
    worker actually calls after extraction."""

    def _entity(self, name: str, entity_type: str = "Person", desc: str = "") -> GraphEntity:
        return GraphEntity(name=name, type=entity_type, description=desc)

    def _rel(self, source: str, target: str, relation: str) -> GraphRelationship:
        return GraphRelationship(source=source, target=target, relation=relation)

    def test_empty_input_returns_empty(self):
        entities, rels = align_batch([], [], [])
        assert entities == []
        assert rels == []

    def test_no_existing_candidates_normalizes_only(self):
        entities, rels = align_batch(
            [self._entity("Jugal Gajjar")],
            [],
            existing_candidates=[],
        )
        assert len(entities) == 1
        assert entities[0].name == "Jugal Gajjar"
        assert entities[0].name_lower == "jugal gajjar"

    def test_deduplicates_within_batch_by_normalized_form(self):
        # Two entities that normalize to the same lower form → one output.
        entities, _ = align_batch(
            [self._entity("Jugal Gajjar"), self._entity("jugal gajjar.")],
            [],
            [],
        )
        assert len(entities) == 1
        assert entities[0].name_lower == "jugal gajjar"

    def test_aliases_to_existing_candidate(self):
        existing = [Candidate(name_lower="jugal gajjar", type="Person")]
        entities, _ = align_batch(
            [self._entity("Jugal V Gajjar", "Person")],
            [],
            existing,
        )
        # Fuzzy match should collapse to the existing name_lower.
        assert len(entities) == 1
        assert entities[0].name_lower == "jugal gajjar"

    def test_second_entity_in_batch_can_alias_to_first(self):
        # "GWU." and "GWU!" both normalize to "gwu"; we get exactly one entity.
        entities, _ = align_batch(
            [
                self._entity("George Washington University", "Organization"),
                self._entity("George   Washington University.", "Organization"),
            ],
            [],
            [],
        )
        assert len(entities) == 1

    def test_same_name_different_types_collapse_first_write_wins(self):
        # Neo4j MERGE key is (user_id, name_lower) — type is not part of
        # the key. So "Apple/Organization" and "Apple/Concept" resolve to
        # the same node; the aligner emits one, and the first-written type
        # sticks (via coalesce in _UPSERT_ENTITY_CYPHER). Documented
        # limitation — see the module docstring.
        entities, _ = align_batch(
            [
                self._entity("Apple", "Organization"),
                self._entity("Apple", "Concept"),
            ],
            [],
            [],
        )
        assert len(entities) == 1
        assert entities[0].type == "Organization"

    def test_type_scoping_prevents_fuzzy_alias_across_types(self):
        # But find_alias itself still type-scopes: an existing "apple" of
        # type Organization does NOT fuzzy-attract "apple pie" of type
        # Concept — they'd stay separate because the fuzzy check bails on
        # type mismatch. (Would still collapse if they normalize identically
        # per the test above.)
        entities, _ = align_batch(
            [self._entity("apple pie", "Concept")],
            [],
            existing_candidates=[Candidate(name_lower="apple", type="Organization")],
        )
        assert len(entities) == 1
        assert entities[0].name_lower == "apple pie"
        assert entities[0].type == "Concept"

    def test_relationship_source_target_rewritten_through_alias(self):
        existing = [Candidate(name_lower="jugal gajjar", type="Person")]
        _, rels = align_batch(
            [
                self._entity("Jugal V Gajjar", "Person"),
                self._entity("George Washington University", "Organization"),
            ],
            [self._rel("Jugal V Gajjar", "George Washington University", "works at")],
            existing,
        )
        assert len(rels) == 1
        # source got aliased to existing candidate; target normalized in-batch.
        assert rels[0].source_lower == "jugal gajjar"
        assert rels[0].target_lower == "george washington university"
        # And the predicate got mapped through L4.
        assert rels[0].relation == "affiliated with"

    def test_drops_relationships_with_missing_endpoint(self):
        # source doesn't appear in the entities list at all → drop.
        _, rels = align_batch(
            [self._entity("A")],
            [self._rel("B", "A", "uses")],
            [],
        )
        assert rels == []

    def test_drops_self_loop_after_alignment(self):
        # Two names that alias to the same node produce a self-loop → drop.
        entities, rels = align_batch(
            [
                self._entity("Jugal Gajjar", "Person"),
                self._entity("jugal gajjar", "Person"),
            ],
            [self._rel("Jugal Gajjar", "jugal gajjar", "same as")],
            [],
        )
        assert len(entities) == 1
        assert rels == []  # self-loop dropped

    def test_deduplicates_relationships_by_key(self):
        # Two rels that reduce to the same (src, tgt, canonical_relation) → 1.
        _, rels = align_batch(
            [self._entity("A"), self._entity("B")],
            [
                self._rel("A", "B", "works at"),
                self._rel("A", "B", "employed by"),  # both map to "affiliated with"
            ],
            [],
        )
        assert len(rels) == 1
        assert rels[0].relation == "affiliated with"

    def test_returns_correct_aligned_types(self):
        # Type is preserved verbatim from the input GraphEntity.
        entities, _ = align_batch([self._entity("X", "Technology")], [], [])
        assert entities[0].type == "Technology"


class TestAlignmentDataclasses:
    """Guard the shape of the exported dataclasses so downstream (worker,
    Neo4j client) doesn't silently break on rename."""

    def test_aligned_entity_fields(self):
        e = AlignedEntity(name="X", name_lower="x", type="Concept", description="d")
        assert e.name == "X" and e.name_lower == "x" and e.type == "Concept"

    def test_aligned_relationship_fields(self):
        r = AlignedRelationship(source_lower="a", target_lower="b", relation="uses")
        assert r.source_lower == "a" and r.target_lower == "b" and r.relation == "uses"
