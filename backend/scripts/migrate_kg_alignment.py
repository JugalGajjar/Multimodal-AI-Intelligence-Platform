"""One-shot migration for #43a: backfill `name_lower` on every existing
:Entity node so the new MERGE key works on the current DB.

After #43a, entities MERGE on (user_id, name_lower). Nodes written before
this migration only have `name`. Without the backfill, any reindex from
that point would create fresh nodes keyed on name_lower and leave the old
ones as orphans (unreachable dupes with the same display name).

Idempotent — safe to re-run. This script:
  1. Ensures the new indexes exist (also done at app startup, harmless).
  2. For each Entity where name_lower IS NULL, computes normalize_name(name)
     and writes it back.
  3. Reports counts per user_id.

Does NOT auto-merge near-duplicates that alignment would have caught if
run at write time — that's a separate, more invasive migration. In
practice, after backfill run `reindex-graph` on each doc (via the UI) to
let alignment collapse dupes on fresh writes.

Usage (from the backend/ directory, with the .env pointing at prod Neo4j):
    python -m scripts.migrate_kg_alignment
"""

from __future__ import annotations

import asyncio
import logging

from app.graph.alignment import normalize_name
from app.graph.neo4j_client import close_driver, ensure_indexes, get_driver

log = logging.getLogger("mmap.migrate_kg_alignment")


async def _run() -> None:
    await ensure_indexes()
    driver = await get_driver()

    async with driver.session() as session:
        # Fetch every entity that hasn't been backfilled yet, keyed by
        # user so we can log per-tenant counts.
        result = await session.run(
            "MATCH (e:Entity) "
            "WHERE e.name_lower IS NULL "
            "RETURN e.user_id AS user_id, e.name AS name, id(e) AS node_id "
            "ORDER BY e.user_id ASC"
        )
        rows = [dict(record) async for record in result]

    if not rows:
        log.info("migrate_kg_alignment: no rows needed backfill — DB already aligned.")
        await close_driver()
        return

    log.info("migrate_kg_alignment: backfilling name_lower on %d entities", len(rows))

    per_user: dict[str, int] = {}
    async with driver.session() as session:
        for row in rows:
            uid = str(row.get("user_id") or "")
            raw = row.get("name") or ""
            nl = normalize_name(raw)
            if not nl:
                # Entity had no usable name — skip; the migration doesn't
                # invent identifiers. Left for manual cleanup.
                log.warning(
                    "migrate_kg_alignment: entity id=%s user=%s has empty normalized name",
                    row["node_id"],
                    uid,
                )
                continue
            await session.run(
                "MATCH (e) WHERE id(e) = $nid SET e.name_lower = $nl",
                nid=row["node_id"],
                nl=nl,
            )
            per_user[uid] = per_user.get(uid, 0) + 1

    for uid, n in sorted(per_user.items()):
        log.info("migrate_kg_alignment: user=%s backfilled=%d", uid, n)
    log.info("migrate_kg_alignment: done.")
    await close_driver()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
