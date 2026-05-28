"""Async Neo4j driver singleton + small query helpers.

Schema (multi-tenant via user_id property):
    (:Entity {user_id, name, type, description, document_ids, ...})
    (a:Entity)-[:RELATES_TO {relation, document_ids}]->(b:Entity)
"""

from __future__ import annotations

from typing import Any

from neo4j import AsyncGraphDatabase  # type: ignore[import-not-found]

from app.core.config import settings

_driver: Any = None


async def get_driver():
    """Process-wide async driver singleton."""
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
        await session.run(
            "CREATE INDEX entity_user_name IF NOT EXISTS FOR (e:Entity) ON (e.user_id, e.name)"
        )


_UPSERT_ENTITY_CYPHER = """
MERGE (e:Entity {user_id: $user_id, name: $name})
ON CREATE SET
    e.type = $type,
    e.description = $description,
    e.created_at = datetime(),
    e.document_ids = [$doc_id]
SET
    e.last_seen_at = datetime(),
    e.type = coalesce(e.type, $type),
    e.description = coalesce(e.description, $description),
    e.document_ids = CASE
        WHEN $doc_id IN coalesce(e.document_ids, []) THEN e.document_ids
        ELSE coalesce(e.document_ids, []) + $doc_id
    END
RETURN e
"""

_UPSERT_REL_CYPHER = """
MATCH (a:Entity {user_id: $user_id, name: $source})
MATCH (b:Entity {user_id: $user_id, name: $target})
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
            type=entity_type,
            description=description,
        )


async def upsert_relationship(
    *,
    user_id: str,
    document_id: str,
    source: str,
    target: str,
    relation: str,
) -> None:
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            _UPSERT_REL_CYPHER,
            user_id=user_id,
            doc_id=document_id,
            source=source,
            target=target,
            relation=relation,
        )


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
    """1-hop neighbours of `entity_name`, in either direction."""
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
    """Return a {nodes, links} snapshot of a user's full graph.

    `nodes` carry display metadata (type, description, document_ids).
    `links` are directed RELATES_TO edges between included nodes. We only
    return edges where BOTH endpoints are in the returned node set so the
    frontend doesn't have to handle dangling refs.
    """
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


async def get_entity_facts(
    user_id: str, names: list[str], *, limit_relations: int = 25
) -> list[dict[str, Any]]:
    """For each entity in `names` belonging to `user_id`, return the entity
    plus its 1-hop neighbours (in either direction) as a flat dict.

    Case-insensitive name matching; the canonical stored name is returned.
    Shape:
        {
          "name": str, "type": str, "description": str,
          "relations": [{"relation": str, "direction": "out"|"in",
                         "other": str, "other_type": str,
                         "other_description": str}, ...]
        }
    """
    if not names:
        return []

    driver = await get_driver()
    lowered = list({n.lower() for n in names})

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Entity {user_id: $user_id})
            WHERE toLower(e.name) IN $lower_names
            OPTIONAL MATCH (e)-[r:RELATES_TO]-(other:Entity)
            WITH e,
                 CASE WHEN startNode(r) = e THEN 'out' ELSE 'in' END AS dir,
                 r.relation AS rel, other
            WITH e, collect({direction: dir, relation: rel,
                             other: other.name, other_type: other.type,
                             other_description: other.description})[..$limit] AS rels
            RETURN
                e.name AS name,
                e.type AS type,
                e.description AS description,
                [x IN rels WHERE x.other IS NOT NULL] AS relations
            """,
            user_id=user_id,
            lower_names=lowered,
            limit=limit_relations,
        )
        return [dict(record) async for record in result]


async def delete_document_traces(user_id: str, document_id: str) -> None:
    """When a document is deleted, prune it from entity/edge document_ids and
    delete entities/edges that no longer point to any document."""
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
        # Also prune doc_id from any surviving relationships
        await session.run(
            "MATCH ()-[r:RELATES_TO]->() "
            "WHERE $doc_id IN coalesce(r.document_ids, []) "
            "SET r.document_ids = [x IN r.document_ids WHERE x <> $doc_id] "
            "WITH r WHERE size(coalesce(r.document_ids, [])) = 0 "
            "DELETE r",
            doc_id=document_id,
        )
