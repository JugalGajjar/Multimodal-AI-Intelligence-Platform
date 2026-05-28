"""Unit tests for graph schema validation + normalization."""

from app.graph.schema import (
    ALLOWED_ENTITY_TYPES,
    ExtractionResult,
    GraphEntity,
    GraphRelationship,
)


class TestNormalize:
    def test_drops_duplicate_entity_names_case_insensitive(self):
        result = ExtractionResult(
            entities=[
                GraphEntity(name="Qdrant", type="Technology"),
                GraphEntity(name="qdrant", type="Technology"),
            ]
        )
        normalized = result.normalize()

        assert len(normalized.entities) == 1
        assert normalized.entities[0].name == "Qdrant"

    def test_drops_relationships_with_dangling_endpoints(self):
        result = ExtractionResult(
            entities=[GraphEntity(name="Qdrant", type="Technology")],
            relationships=[
                GraphRelationship(source="Qdrant", target="MissingEntity", relation="uses"),
                GraphRelationship(source="Other", target="Qdrant", relation="powers"),
            ],
        )
        normalized = result.normalize()

        assert normalized.relationships == []

    def test_keeps_relationships_when_both_endpoints_exist(self):
        result = ExtractionResult(
            entities=[
                GraphEntity(name="Qdrant", type="Technology"),
                GraphEntity(name="Cosine Distance", type="Concept"),
            ],
            relationships=[
                GraphRelationship(source="Qdrant", target="Cosine Distance", relation="uses"),
            ],
        )
        normalized = result.normalize()

        assert len(normalized.relationships) == 1
        assert normalized.relationships[0].source == "Qdrant"
        assert normalized.relationships[0].target == "Cosine Distance"

    def test_drops_self_loops(self):
        result = ExtractionResult(
            entities=[GraphEntity(name="Qdrant", type="Technology")],
            relationships=[GraphRelationship(source="Qdrant", target="qdrant", relation="is")],
        )
        assert result.normalize().relationships == []

    def test_drops_duplicate_relationships(self):
        result = ExtractionResult(
            entities=[
                GraphEntity(name="A", type="Concept"),
                GraphEntity(name="B", type="Concept"),
            ],
            relationships=[
                GraphRelationship(source="A", target="B", relation="uses"),
                GraphRelationship(source="a", target="b", relation="USES"),
            ],
        )
        assert len(result.normalize().relationships) == 1

    def test_coerces_unknown_entity_type_to_concept(self):
        result = ExtractionResult(
            entities=[GraphEntity(name="X", type="Vegetable")],
        )
        normalized = result.normalize()

        assert normalized.entities[0].type == "Concept"

    def test_keeps_allowed_types(self):
        for t in ALLOWED_ENTITY_TYPES:
            result = ExtractionResult(
                entities=[GraphEntity(name=f"X-{t}", type=t)],
            )
            assert result.normalize().entities[0].type == t

    def test_empty_input_is_empty_output(self):
        assert ExtractionResult().normalize() == ExtractionResult()
