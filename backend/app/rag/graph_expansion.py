"""Expand retrieval with knowledge-graph facts the user has stored.

Two complementary sources:

1. **Name-matched** — case-insensitive substring match between the user's
   stored entity names and a haystack made of (query + retrieved chunk text).
   Highest priority: if the question or evidence literally mentions an entity,
   we want it.

2. **Document-scoped** — entities tagged with at least one `document_id` from
   the retrieved chunks. Surfaces graph context tied to the evidence even
   when the question doesn't say the entity name out loud.

The union (name-matches first) is deduped, capped, and resolved to facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.graph.neo4j_client import (
    get_entity_facts,
    list_entity_names_for_documents,
    list_user_entities,
)
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


def _document_ids_from_chunks(chunks: list[RetrievedChunk]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for c in chunks:
        if c.document_id and c.document_id not in seen:
            seen.add(c.document_id)
            ordered.append(c.document_id)
    return ordered


def _merge_unique(*sources: list[str]) -> list[str]:
    """Concatenate string lists, dedupe case-insensitively, keep first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        for name in source:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
    return out


async def expand_with_graph(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    user_id: UUID,
    max_entities: int = 8,
    max_relations_per_entity: int = 6,
) -> list[GraphFact]:
    """Return GraphFact objects for entities tied to this turn.

    Sources, in priority order:
      1. Entity names that literally appear in the user's question or in the
         retrieved chunk text.
      2. Entity names attached to documents that the vector search returned
         (graph context for the evidence).

    Returns [] when the user has no graph yet OR neither source yields any
    entity tied to the current turn.
    """
    candidates = await list_user_entities(str(user_id), limit=500)
    if not candidates:
        return []

    haystack = _build_haystack(query, chunks)
    name_matched = _match_entities(haystack, candidates, max_matches=max_entities)

    doc_scoped: list[str] = []
    doc_ids = _document_ids_from_chunks(chunks)
    if doc_ids:
        doc_scoped = await list_entity_names_for_documents(
            str(user_id), doc_ids, limit=max_entities * 4
        )

    target_names = _merge_unique(name_matched, doc_scoped)[:max_entities]
    if not target_names:
        return []

    raw = await get_entity_facts(
        str(user_id), target_names, limit_relations=max_relations_per_entity
    )

    # Preserve our preferred order (name-matched first) instead of whatever
    # the cypher returned.
    raw_by_lower = {row["name"].lower(): row for row in raw}

    facts: list[GraphFact] = []
    for name in target_names:
        row = raw_by_lower.get(name.lower())
        if row is None:
            continue
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
