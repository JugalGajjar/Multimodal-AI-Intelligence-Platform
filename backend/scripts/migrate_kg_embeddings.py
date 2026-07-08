"""One-shot migration for #43c: backfill `embedding` on every existing
:Entity node so L3 semantic alignment has candidates to compare against.

Idempotent — safe to re-run. Rows already carrying an embedding are skipped.
Batches embedding calls through the same bge-small model retrieval uses.

Usage (from the backend/ directory, with the .env pointing at prod Neo4j):
    python -m scripts.migrate_kg_embeddings
"""

from __future__ import annotations

import asyncio
import logging

from app.embeddings import embed_texts
from app.graph.neo4j_client import close_driver, ensure_indexes, get_driver
from app.graph.semantic_alignment import format_entity_text

log = logging.getLogger("mmap.migrate_kg_embeddings")

BATCH_SIZE = 128  # bge-small handles this comfortably on CPU


async def _run() -> None:
    await ensure_indexes()
    driver = await get_driver()

    async with driver.session() as session:
        # Every entity missing an embedding, keyed by internal node id for the
        # write-back step below. `coalesce` guards against nulls in description.
        result = await session.run(
            "MATCH (e:Entity) "
            "WHERE e.embedding IS NULL "
            "RETURN id(e) AS node_id, e.name AS name, "
            "coalesce(e.description, '') AS description, e.user_id AS user_id"
        )
        rows = [dict(record) async for record in result]

    if not rows:
        log.info("migrate_kg_embeddings: no rows needed backfill — every entity has an embedding.")
        await close_driver()
        return

    log.info("migrate_kg_embeddings: embedding %d entities in batches of %d", len(rows), BATCH_SIZE)

    per_user: dict[str, int] = {}
    async with driver.session() as session:
        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]
            texts = [format_entity_text(r["name"], r["description"]) for r in batch]
            # Runs in the current thread — this is a one-shot admin script,
            # blocking is fine.
            vectors = embed_texts(texts)

            for row, vec in zip(batch, vectors, strict=True):
                await session.run(
                    "MATCH (e) WHERE id(e) = $nid SET e.embedding = $emb",
                    nid=row["node_id"],
                    emb=vec,
                )
                uid = str(row.get("user_id") or "")
                per_user[uid] = per_user.get(uid, 0) + 1

            log.info(
                "migrate_kg_embeddings: batch %d/%d done",
                batch_start // BATCH_SIZE + 1,
                (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE,
            )

    for uid, n in sorted(per_user.items()):
        log.info("migrate_kg_embeddings: user=%s backfilled=%d", uid, n)
    log.info("migrate_kg_embeddings: done.")
    await close_driver()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
