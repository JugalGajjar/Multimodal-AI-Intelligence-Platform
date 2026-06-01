"""Expand retrieval with graph facts about entities tied to this turn.

Two sources, name-matches first:
  1. Entity names that appear in the question or retrieved chunk text.
  2. Entities tagged with a document_id from the retrieved chunks.

The union is deduped, capped, and resolved to multi-hop facts via the
shortest path; closer hops win when the per-seed cap drops long chains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.core.config import settings
from app.graph.neo4j_client import (
    get_entity_facts,
    list_entity_names_for_documents,
    list_user_entities,
)
from app.rag.retrieval import RetrievedChunk


@dataclass(frozen=True)
class GraphRelation:
    """A fact about an entity's relationship to another entity.

    For 1-hop facts, `relation_chain` is a single-element list and `distance`
    is 1. For multi-hop facts, the chain describes the shortest path:
        Bandit --(used by)--> SecureFixAgent --(repairs)--> Vulnerability
    would surface as `relation_chain=["used by", "repairs"]`, `distance=2`,
    `other="Vulnerability"`.

    `direction` ("in" | "out") is meaningful for 1-hop only; multi-hop walks
    are undirected and default to "out".
    """

    relation: str  # joined chain, e.g. "uses → part of"
    other: str
    other_type: str = ""
    other_description: str = ""
    distance: int = 1
    relation_chain: list[str] = field(default_factory=list)
    direction: str = "out"


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


def _clamp_hops(value: int) -> int:
    return max(1, min(3, value))


def _build_relation(raw: dict) -> GraphRelation | None:
    """Normalize a row from `get_entity_facts` into a GraphRelation.

    Skips rows whose endpoint or chain is empty.
    """
    other = raw.get("other")
    chain = raw.get("relation_chain") or []
    # Drop any falsy individual edges to keep "→" rendering tidy.
    chain = [str(r).strip() for r in chain if r]
    if not other or not chain:
        return None
    return GraphRelation(
        relation=" → ".join(chain),
        other=str(other),
        other_type=raw.get("other_type") or "",
        other_description=raw.get("other_description") or "",
        distance=int(raw.get("distance") or len(chain) or 1),
        relation_chain=chain,
        direction=raw.get("direction") or "out",
    )


async def expand_with_graph(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    user_id: UUID,
    max_entities: int = 8,
    max_hops: int | None = None,
    max_facts_per_seed: int | None = None,
) -> list[GraphFact]:
    # Returns [] when the user has no graph or neither source surfaces an
    # entity tied to this turn. `max_hops` defaults to settings.graph_max_hops.
    hops = _clamp_hops(max_hops if max_hops is not None else settings.graph_max_hops)
    per_seed = (
        max_facts_per_seed if max_facts_per_seed is not None else settings.graph_max_facts_per_seed
    )

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
        str(user_id),
        target_names,
        max_hops=hops,
        max_facts_per_seed=per_seed,
    )

    # Preserve our preferred order (name-matched first) instead of whatever
    # the cypher returned.
    raw_by_lower = {row["name"].lower(): row for row in raw}

    facts: list[GraphFact] = []
    for name in target_names:
        row = raw_by_lower.get(name.lower())
        if row is None:
            continue
        rels: list[GraphRelation] = []
        for raw_rel in row.get("relations") or []:
            built = _build_relation(raw_rel)
            if built is not None:
                rels.append(built)
        facts.append(
            GraphFact(
                name=row["name"],
                type=row.get("type") or "Concept",
                description=row.get("description") or "",
                relations=rels,
            )
        )
    return facts
