"""Pydantic models for entity-extraction output and graph storage."""

from pydantic import BaseModel, Field

ALLOWED_ENTITY_TYPES = (
    "Person",
    "Organization",
    "Location",
    "Concept",
    "Technology",
    "Product",
    "Event",
    "Date",
)


class GraphEntity(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(default="Concept", max_length=64)
    description: str = Field(default="", max_length=500)


class GraphRelationship(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=120)


class ExtractionResult(BaseModel):
    entities: list[GraphEntity] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)

    def normalize(self) -> "ExtractionResult":
        """Drop relationships whose endpoints aren't in entities, dedup, trim."""
        seen_names: set[str] = set()
        clean_entities: list[GraphEntity] = []
        for e in self.entities:
            key = e.name.strip()
            if not key or key.lower() in {n.lower() for n in seen_names}:
                continue
            seen_names.add(key)
            clean_entities.append(
                GraphEntity(
                    name=key,
                    type=e.type if e.type in ALLOWED_ENTITY_TYPES else "Concept",
                    description=e.description.strip(),
                )
            )

        clean_rels: list[GraphRelationship] = []
        lc_names = {n.lower() for n in seen_names}
        seen_rels: set[tuple[str, str, str]] = set()
        for r in self.relationships:
            s, t, rel = r.source.strip(), r.target.strip(), r.relation.strip()
            if s.lower() not in lc_names or t.lower() not in lc_names:
                continue
            if s.lower() == t.lower():
                continue
            key3 = (s.lower(), t.lower(), rel.lower())
            if key3 in seen_rels:
                continue
            seen_rels.add(key3)
            clean_rels.append(GraphRelationship(source=s, target=t, relation=rel))

        return ExtractionResult(entities=clean_entities, relationships=clean_rels)
