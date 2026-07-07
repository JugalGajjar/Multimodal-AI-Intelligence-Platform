"""Async Neo4j driver singleton + small query helpers.

Schema (multi-tenant via user_id property):
    (:Entity {user_id, name, name_lower, type, description, document_ids, ...})
    (a:Entity)-[:RELATES_TO {relation, document_ids}]->(b:Entity)

Entities MERGE on (user_id, name_lower) so alignment collapses case/spacing
variants into one node. `name` is the display form (first-write wins).
Relationships MERGE on (source name_lower, target name_lower, relation).
See app.graph.alignment for how raw extraction names get normalized.
"""

from __future__ import annotations

from typing import Any

from neo4j import AsyncGraphDatabase  # type: ignore[import-not-found]

from app.core.config import settings

_driver: Any = None


async def get_driver():
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def ensure_indexes() -> None:
    driver = await get_driver()
    async with driver.session() as session:
        # Primary MERGE key since #43a — alignment layer collapses variants
        # into one canonical name_lower per user.
        await session.run(
            "CREATE INDEX entity_user_name_lower IF NOT EXISTS "
            "FOR (e:Entity) ON (e.user_id, e.name_lower)"
        )
        # Legacy index on `name` — kept for the display-name lookups the
        # read paths still use (get_graph_snapshot, list_user_entities).
        # The migration script backfills name_lower on existing entities.
        await session.run(
            "CREATE INDEX entity_user_name IF NOT EXISTS FOR (e:Entity) ON (e.user_id, e.name)"
        )


_UPSERT_ENTITY_CYPHER = """
MERGE (e:Entity {user_id: $user_id, name_lower: $name_lower})
ON CREATE SET
    e.name = $name,
    e.type = $type,
    e.description = $description,
    e.created_at = datetime(),
    e.document_ids = [$doc_id]
SET
    e.last_seen_at = datetime(),
    e.name = coalesce(e.name, $name),
    e.type = coalesce(e.type, $type),
    e.description = coalesce(e.description, $description),
    e.document_ids = CASE
        WHEN $doc_id IN coalesce(e.document_ids, []) THEN e.document_ids
        ELSE coalesce(e.document_ids, []) + $doc_id
    END
RETURN e
"""

_UPSERT_REL_CYPHER = """
MATCH (a:Entity {user_id: $user_id, name_lower: $source_lower})
MATCH (b:Entity {user_id: $user_id, name_lower: $target_lower})
MERGE (a)-[r:RELATES_TO {relation: $relation}]->(b)
ON CREATE SET r.created_at = datetime(), r.document_ids = [$doc_id]
SET r.document_ids = CASE
    WHEN $doc_id IN coalesce(r.document_ids, []) THEN r.document_ids
    ELSE coalesce(r.document_ids, []) + $doc_id
END
RETURN r
"""


async def upsert_entity(
    *,
    user_id: str,
    document_id: str,
    name: str,
    name_lower: str,
    entity_type: str,
    description: str,
) -> None:
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            _UPSERT_ENTITY_CYPHER,
            user_id=user_id,
            doc_id=document_id,
            name=name,
            name_lower=name_lower,
            type=entity_type,
            description=description,
        )


async def upsert_relationship(
    *,
    user_id: str,
    document_id: str,
    source_lower: str,
    target_lower: str,
    relation: str,
) -> None:
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            _UPSERT_REL_CYPHER,
            user_id=user_id,
            doc_id=document_id,
            source_lower=source_lower,
            target_lower=target_lower,
            relation=relation,
        )


async def list_entity_candidates(user_id: str) -> list[tuple[str, str]]:
    """Return (name_lower, type) tuples for every entity the user owns.

    Used by alignment.align_batch as the pool of candidates that a new
    entity may alias to. Small payload per row — cheap even with a few
    thousand entities. See app.graph.alignment.Candidate.
    """
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (e:Entity {user_id: $user_id}) "
            "WHERE e.name_lower IS NOT NULL "
            "RETURN e.name_lower AS name_lower, coalesce(e.type, 'Concept') AS type",
            user_id=user_id,
        )
        return [(row["name_lower"], row["type"]) async for row in result]


async def list_user_entities(user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (e:Entity {user_id: $user_id}) "
            "RETURN e.name AS name, e.type AS type, "
            "e.description AS description, e.document_ids AS document_ids "
            "ORDER BY e.last_seen_at DESC LIMIT $limit",
            user_id=user_id,
            limit=limit,
        )
        return [dict(record) async for record in result]


async def list_relationships_for_entity(
    user_id: str, entity_name: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    # 1-hop neighbours in either direction.
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (a:Entity {user_id: $user_id, name: $name})-[r:RELATES_TO]-(b:Entity) "
            "RETURN a.name AS source, b.name AS target, r.relation AS relation, "
            "b.type AS target_type, b.description AS target_description "
            "LIMIT $limit",
            user_id=user_id,
            name=entity_name,
            limit=limit,
        )
        return [dict(record) async for record in result]


async def get_graph_snapshot(
    user_id: str, *, limit_nodes: int = 500, limit_links: int = 2000
) -> dict[str, list[dict[str, Any]]]:
    # Returns only edges where both endpoints are in the node set, so the
    # frontend never sees dangling refs.
    driver = await get_driver()
    async with driver.session() as session:
        nodes_result = await session.run(
            """
            MATCH (e:Entity {user_id: $user_id})
            RETURN
                e.name AS id,
                e.name AS name,
                coalesce(e.type, 'Concept') AS type,
                coalesce(e.description, '') AS description,
                coalesce(e.document_ids, []) AS document_ids
            ORDER BY e.last_seen_at DESC
            LIMIT $limit
            """,
            user_id=user_id,
            limit=limit_nodes,
        )
        nodes = [dict(r) async for r in nodes_result]

        if not nodes:
            return {"nodes": [], "links": []}

        ids = {n["id"] for n in nodes}
        links_result = await session.run(
            """
            MATCH (a:Entity {user_id: $user_id})-[r:RELATES_TO]->(b:Entity {user_id: $user_id})
            WHERE a.name IN $names AND b.name IN $names
            RETURN a.name AS source, b.name AS target, r.relation AS relation
            LIMIT $limit
            """,
            user_id=user_id,
            names=list(ids),
            limit=limit_links,
        )
        links = [dict(r) async for r in links_result]

    return {"nodes": nodes, "links": links}


async def list_entity_names_for_documents(
    user_id: str, document_ids: list[str], *, limit: int = 200
) -> list[str]:
    # Most-recently-seen first; capped by `limit`.
    if not document_ids:
        return []
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Entity {user_id: $user_id})
            WHERE any(d IN $doc_ids WHERE d IN coalesce(e.document_ids, []))
            RETURN e.name AS name
            ORDER BY e.last_seen_at DESC
            LIMIT $limit
            """,
            user_id=user_id,
            doc_ids=document_ids,
            limit=limit,
        )
        return [row["name"] async for row in result]


_MAX_SUPPORTED_HOPS = 3


def _build_facts_cypher(max_hops: int) -> str:
    # Cypher's *1..N requires a literal int, so we template it; validated
    # against _MAX_SUPPORTED_HOPS to keep the format string safe.
    if max_hops < 1 or max_hops > _MAX_SUPPORTED_HOPS:
        raise ValueError(f"max_hops must be in 1..{_MAX_SUPPORTED_HOPS}, got {max_hops}")
    return f"""
    UNWIND $lower_names AS seed_lower
    MATCH (e:Entity {{user_id: $user_id}})
    WHERE toLower(e.name) = seed_lower
    OPTIONAL MATCH path = (e)-[rels:RELATES_TO*1..{max_hops}]-(other:Entity {{user_id: $user_id}})
    WHERE other IS NULL OR other.name <> e.name
    WITH e, other, length(path) AS dist, [r IN rels | r.relation] AS rel_chain
    ORDER BY dist ASC
    WITH e, other,
         head(collect({{dist: dist, rels: rel_chain}})) AS shortest
    WITH e,
         collect(
            CASE WHEN other IS NULL THEN NULL
            ELSE {{
              other: other.name,
              other_type: other.type,
              other_description: other.description,
              distance: shortest.dist,
              relation_chain: shortest.rels
            }} END
         ) AS all_rels
    WITH e, [x IN all_rels WHERE x IS NOT NULL] AS rels_filtered
    RETURN
        e.name AS name,
        e.type AS type,
        e.description AS description,
        rels_filtered[..$facts_per_seed] AS relations
    """


async def get_entity_facts(
    user_id: str,
    names: list[str],
    *,
    max_hops: int = 1,
    max_facts_per_seed: int = 12,
) -> list[dict[str, Any]]:
    # Keeps the shortest path per neighbour so the per-seed cap drops the
    # long-distance noise first. Name matching is case-insensitive; returned
    # names are the canonical stored form.
    if not names:
        return []

    driver = await get_driver()
    lowered = list({n.lower() for n in names})

    cypher = _build_facts_cypher(max_hops)
    async with driver.session() as session:
        result = await session.run(
            cypher,
            user_id=user_id,
            lower_names=lowered,
            facts_per_seed=max_facts_per_seed,
        )
        return [dict(record) async for record in result]


async def delete_document_traces(user_id: str, document_id: str) -> None:
    # Prune doc_id from entities/edges and delete those left orphaned.
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (e:Entity {user_id: $user_id}) "
            "WHERE $doc_id IN coalesce(e.document_ids, []) "
            "SET e.document_ids = [x IN e.document_ids WHERE x <> $doc_id] "
            "WITH e WHERE size(coalesce(e.document_ids, [])) = 0 "
            "DETACH DELETE e",
            user_id=user_id,
            doc_id=document_id,
        )
        # Prune doc_id from surviving relationships too.
        await session.run(
            "MATCH ()-[r:RELATES_TO]->() "
            "WHERE $doc_id IN coalesce(r.document_ids, []) "
            "SET r.document_ids = [x IN r.document_ids WHERE x <> $doc_id] "
            "WITH r WHERE size(coalesce(r.document_ids, [])) = 0 "
            "DELETE r",
            doc_id=document_id,
        )
