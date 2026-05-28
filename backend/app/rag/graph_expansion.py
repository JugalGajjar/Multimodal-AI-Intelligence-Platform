"""Find entities from the user's knowledge graph that are mentioned in the
retrieved chunks or the user's query, and pull their 1-hop neighbours.

Heuristic: case-insensitive substring match between the user's stored
entity names and the haystack text. Cheap and effective for the small
per-user graphs we expect; can be upgraded to a proper NER pass later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.graph.neo4j_client import get_entity_facts, list_user_entities
from app.rag.retrieval import RetrievedChunk


@dataclass(frozen=True)
class GraphRelation:
    relation: str
    direction: str  # "out" | "in"
    other: str
    other_type: str = ""
    other_description: str = ""


@dataclass(frozen=True)
class GraphFact:
    name: str
    type: str
    description: str
    relations: list[GraphRelation] = field(default_factory=list)


def _build_haystack(query: str, chunks: list[RetrievedChunk]) -> str:
    parts = [query]
    parts.extend(c.text for c in chunks)
    return " ".join(parts).lower()


def _match_entities(haystack: str, candidates: list[dict], *, max_matches: int = 12) -> list[str]:
    """Substring-match candidate entity names against the haystack.

    Sort matches longest-name first so multi-word names take precedence over
    their shorter substrings (e.g. "Cosine Distance" before "Cosine").
    """
    sorted_by_len = sorted(candidates, key=lambda e: -len(e["name"]))
    matched: list[str] = []
    used_lower: set[str] = set()
    for e in sorted_by_len:
        name = e["name"]
        if len(name) < 3:
            continue
        lower = name.lower()
        if lower in used_lower:
            continue
        if lower in haystack:
            matched.append(name)
            used_lower.add(lower)
            if len(matched) >= max_matches:
                break
    return matched


async def expand_with_graph(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    user_id: UUID,
    max_entities: int = 8,
    max_relations_per_entity: int = 6,
) -> list[GraphFact]:
    """Return GraphFact objects for entities mentioned in the query or
    retrieved chunks. Empty list when the user has no graph yet."""
    candidates = await list_user_entities(str(user_id), limit=500)
    if not candidates:
        return []

    haystack = _build_haystack(query, chunks)
    matched_names = _match_entities(haystack, candidates, max_matches=max_entities)
    if not matched_names:
        return []

    raw = await get_entity_facts(
        str(user_id), matched_names, limit_relations=max_relations_per_entity
    )

    facts: list[GraphFact] = []
    for row in raw:
        rels = [
            GraphRelation(
                relation=r.get("relation") or "",
                direction=r.get("direction") or "out",
                other=r.get("other") or "",
                other_type=r.get("other_type") or "",
                other_description=r.get("other_description") or "",
            )
            for r in (row.get("relations") or [])
            if (r.get("other") and r.get("relation"))
        ]
        facts.append(
            GraphFact(
                name=row["name"],
                type=row.get("type") or "Concept",
                description=row.get("description") or "",
                relations=rels[:max_relations_per_entity],
            )
        )
    return facts
