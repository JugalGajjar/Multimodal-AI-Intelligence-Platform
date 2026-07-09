"""arq tasks. Heavy ML imports live in app.workers.ocr.* (worker image only)."""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_maker
from app.documents.chunks_model import DocumentChunk
from app.documents.models import Document, DocumentStatus
from app.storage.minio_client import get_minio_client

log = logging.getLogger("mmap.worker")


async def process_document_ocr(ctx: dict[str, Any], document_id: str) -> str:
    # OCR → chunk → embed → Qdrant → graph → summary.
    from app.embeddings import embed_texts
    from app.workers.chunking import chunk_text, is_meaningful
    from app.workers.ocr.pipeline import extract_text_from_bytes

    async with async_session_maker() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            log.warning("process_document_ocr: doc %s not found", document_id)
            return "missing"

        doc.status = DocumentStatus.PROCESSING
        await db.commit()
        await db.refresh(doc)

        try:
            data = await asyncio.to_thread(_download_bytes, doc.storage_key)
            text = await extract_text_from_bytes(
                data,
                doc.content_type,
                filename=doc.filename,
            )
            doc.extracted_text = text

            raw_chunks = chunk_text(text) if text.strip() else []
            # Drop OCR/PDF noise that would otherwise pollute retrieval. Only
            # filter when the doc produced more than one chunk — for short
            # transcripts (audio, voice notes) we'd rather index a small chunk
            # than nothing.
            if len(raw_chunks) > 1:
                chunks = [c for c in raw_chunks if is_meaningful(c.text)]
            else:
                chunks = raw_chunks
            log.info(
                "doc=%s ocr=%d chars chunks=%d (filtered %d noise)",
                document_id,
                len(text),
                len(chunks),
                len(raw_chunks) - len(chunks),
            )

            chunk_rows: list[DocumentChunk] = []
            for c in chunks:
                row = DocumentChunk(
                    id=uuid4(),
                    document_id=doc.id,
                    chunk_index=c.index,
                    text=c.text,
                    char_start=c.char_start,
                    char_end=c.char_end,
                )
                chunk_rows.append(row)
                db.add(row)
            await db.flush()

            if chunk_rows:
                vectors = await asyncio.to_thread(embed_texts, [r.text for r in chunk_rows])
                await asyncio.to_thread(
                    _upsert_qdrant_points,
                    chunk_rows=chunk_rows,
                    vectors=vectors,
                    user_id=str(doc.user_id),
                    document_id=str(doc.id),
                )

            doc.status = DocumentStatus.PROCESSED
            await db.commit()

            # Graph + summary are best-effort. Vector RAG still works without
            # them, so failures here must not fail the document.
            if text.strip():
                await _ingest_graph(
                    chunks=[r.text for r in chunk_rows] or [text],
                    user_id=str(doc.user_id),
                    document_id=str(doc.id),
                )
                await _summarize_and_store(text=text, document_id=str(doc.id))
            return "processed"

        except (Exception, asyncio.CancelledError) as exc:
            # asyncio.CancelledError is a BaseException in 3.8+, so plain
            # `except Exception` missed it — arq's job-timeout cancel would
            # bypass this handler entirely and leave the doc row wedged at
            # `processing` forever. Catch both and re-raise CancelledError
            # after our cleanup so arq still records the timeout correctly.
            timed_out = isinstance(exc, asyncio.CancelledError)
            log.exception("ocr pipeline failed for doc=%s", document_id)
            # Discard pending chunk inserts so we don't persist orphan rows
            # whose vectors never reached Qdrant.
            try:
                await db.rollback()
                failed_doc = await db.get(Document, document_id)
                if failed_doc is not None:
                    failed_doc.status = DocumentStatus.FAILED
                    failed_doc.error_message = (
                        "OCR timed out — try a smaller or text-based PDF."
                        if timed_out
                        else str(exc)
                    )
                    await db.commit()
            except Exception:
                log.exception("failed to record failure status for doc=%s", document_id)
            if timed_out:
                # Let arq see the cancel so its own bookkeeping stays right.
                raise
            return "failed"


def _download_bytes(storage_key: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(settings.minio_bucket, storage_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _upsert_qdrant_points(
    *,
    chunk_rows: list[DocumentChunk],
    vectors: list[list[float]],
    user_id: str,
    document_id: str,
) -> None:
    from qdrant_client.http import models as qmodels

    from app.rag.sparse import SPARSE_VECTOR_NAME, encode_passages
    from app.storage.qdrant_client import (
        COLLECTION_NAME,
        DENSE_VECTOR_NAME,
        ensure_collection,
        get_qdrant_client,
    )

    ensure_collection()
    client = get_qdrant_client()

    sparse_vectors = encode_passages([row.text for row in chunk_rows])

    points = [
        qmodels.PointStruct(
            id=str(row.id),
            vector={
                DENSE_VECTOR_NAME: vec,
                SPARSE_VECTOR_NAME: qmodels.SparseVector(indices=s_idx, values=s_val),
            },
            payload={
                "chunk_id": str(row.id),
                "document_id": document_id,
                "user_id": user_id,
                "chunk_index": row.chunk_index,
                "text": row.text,
            },
        )
        for row, vec, (s_idx, s_val) in zip(chunk_rows, vectors, sparse_vectors, strict=True)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)


GRAPH_EXTRACT_MAX_ATTEMPTS = 3
GRAPH_EXTRACT_BACKOFF_SECONDS = (15, 30)  # sleep between attempt 1→2 and 2→3


async def _ingest_graph(*, chunks: list[str], user_id: str, document_id: str) -> None:
    # Best-effort: swallow errors so the worker stays non-blocking.
    try:
        from app.embeddings import embed_texts
        from app.graph.alignment import (
            AlignedEntity,
            AlignedRelationship,
            Candidate,
            align_batch,
        )
        from app.graph.extraction import safe_extract_entities
        from app.graph.neo4j_client import (
            ensure_indexes,
            list_entity_candidates,
            list_entity_semantic_candidates,
            upsert_entity,
            upsert_relationship,
        )
        from app.graph.semantic_alignment import (
            SemanticCandidate,
            find_semantic_alias,
            format_entity_text,
        )

        # Groq's json_object validator flakes intermittently — the same
        # extraction that returned 0 entities on upload will often return
        # 20+ on a manual reindex 60-120s later. Retry transient failures
        # in-line so the user's graph populates without a manual click.
        outcome = await safe_extract_entities(chunks)
        for attempt in range(2, GRAPH_EXTRACT_MAX_ATTEMPTS + 1):
            if outcome.result.entities or not outcome.transient_failure:
                break
            sleep_for = GRAPH_EXTRACT_BACKOFF_SECONDS[attempt - 2]
            log.info(
                "graph: transient extraction failure on doc=%s (attempt %d/%d) — sleeping %ds",
                document_id,
                attempt - 1,
                GRAPH_EXTRACT_MAX_ATTEMPTS,
                sleep_for,
            )
            await asyncio.sleep(sleep_for)
            outcome = await safe_extract_entities(chunks)

        if not outcome.result.entities:
            log.info(
                "graph: no entities extracted for doc=%s (transient=%s)",
                document_id,
                outcome.transient_failure,
            )
            return
        result = outcome.result

        await ensure_indexes()

        # Alignment (#43a): pull the user's existing entities as fuzzy-match
        # candidates so this doc's writes converge on the shared KG instead
        # of creating parallel islands ("GWU" vs "gwu.", "Kamalasankaris" vs
        # "Kamalasankari" etc.). One Neo4j fetch per doc; the aligner runs
        # in-memory from there.
        existing_pairs = await list_entity_candidates(user_id)
        existing = [Candidate(name_lower=nl, type=t) for nl, t in existing_pairs]
        aligned_entities, aligned_rels = align_batch(
            result.entities,
            result.relationships,
            existing,
        )
        pre_l3_ent_count = len(aligned_entities)
        pre_l3_rel_count = len(aligned_rels)

        # Semantic alignment (#43c): L3 layer on top of L1/L2. Embed each
        # aligned entity's `name: description`, compare cosine similarity
        # against existing same-type entities' stored embeddings. If a
        # match clears the threshold, rewrite the entity's name_lower to
        # the existing canonical form and cascade the change through the
        # relationships. Catches abbreviation/expansion pairs (SFT ↔
        # Supervised Fine-Tuning) that L1/L2 string-fuzzy can't.
        entity_embeddings: dict[str, list[float]] = {}
        if settings.graph_semantic_align and aligned_entities:
            existing_semantic = await list_entity_semantic_candidates(user_id)
            running_candidates = [
                SemanticCandidate(
                    name_lower=nl,
                    type=t,
                    embedding=tuple(emb),
                )
                for nl, t, emb in existing_semantic
            ]
            texts = [format_entity_text(e.name, e.description) for e in aligned_entities]
            embeddings = await asyncio.to_thread(embed_texts, texts)
            alias_map: dict[str, str] = {}  # old name_lower → canonical
            for e, emb in zip(aligned_entities, embeddings, strict=True):
                match = find_semantic_alias(
                    emb,
                    e.type,
                    running_candidates,
                    settings.graph_semantic_threshold_same,
                    settings.graph_semantic_threshold_cross,
                )
                if match and match != e.name_lower:
                    alias_map[e.name_lower] = match
                else:
                    # Not aliased — this entity becomes a candidate that
                    # later same-batch entities (or future docs) can align to.
                    running_candidates.append(
                        SemanticCandidate(
                            name_lower=e.name_lower,
                            type=e.type,
                            embedding=tuple(emb),
                        )
                    )
                    entity_embeddings[e.name_lower] = emb

            if alias_map:
                seen: set[str] = set()
                collapsed: list[AlignedEntity] = []
                for e in aligned_entities:
                    canonical = alias_map.get(e.name_lower, e.name_lower)
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    if canonical == e.name_lower:
                        collapsed.append(e)
                    else:
                        # Aliased into a canonical form — keep the aliased
                        # display name; ON CREATE on the existing node is
                        # a no-op so display stays as first-write.
                        collapsed.append(
                            AlignedEntity(
                                name=e.name,
                                name_lower=canonical,
                                type=e.type,
                                description=e.description,
                            )
                        )
                aligned_entities = collapsed

                rewritten_rels: list[AlignedRelationship] = []
                for r in aligned_rels:
                    src = alias_map.get(r.source_lower, r.source_lower)
                    tgt = alias_map.get(r.target_lower, r.target_lower)
                    if src == tgt:
                        continue  # self-loop after L3
                    rewritten_rels.append(
                        AlignedRelationship(
                            source_lower=src,
                            target_lower=tgt,
                            relation=r.relation,
                        )
                    )
                aligned_rels = rewritten_rels

        for e in aligned_entities:
            await upsert_entity(
                user_id=user_id,
                document_id=document_id,
                name=e.name,
                name_lower=e.name_lower,
                entity_type=e.type,
                description=e.description,
                embedding=entity_embeddings.get(e.name_lower),
            )
        for r in aligned_rels:
            await upsert_relationship(
                user_id=user_id,
                document_id=document_id,
                source_lower=r.source_lower,
                target_lower=r.target_lower,
                relation=r.relation,
            )
        log.info(
            "graph: doc=%s chunks=%d entities=%d rels=%d "
            "(pre-l3 %d ents, %d rels; raw %d ents, %d rels)",
            document_id,
            len(chunks),
            len(aligned_entities),
            len(aligned_rels),
            pre_l3_ent_count,
            pre_l3_rel_count,
            len(result.entities),
            len(result.relationships),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("graph ingest failed (non-blocking): %s", exc)


async def _summarize_and_store(*, text: str, document_id: str) -> None:
    # Best-effort: failure leaves the existing summary columns untouched.
    try:
        from app.agents.summarization import summarize_document

        result = await summarize_document(text)
        if result.is_empty():
            log.info("summary: no content produced for doc=%s", document_id)
            return

        async with async_session_maker() as db:
            doc = await db.get(Document, document_id)
            if doc is None:
                return
            doc.summary_tldr = result.tldr or None
            doc.summary_key_points = list(result.key_points) or None
            doc.summary_topics = list(result.topics) or None
            await db.commit()
        log.info(
            "summary: doc=%s tldr=%d chars points=%d topics=%d",
            document_id,
            len(result.tldr),
            len(result.key_points),
            len(result.topics),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("summarization failed (non-blocking): %s", exc)


async def resummarize_document(ctx: dict[str, Any], document_id: str) -> str:
    # Re-run summarization on stored chunks. No re-OCR or re-embed.
    async with async_session_maker() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return "missing"

        if str(doc.status) != DocumentStatus.PROCESSED.value:
            log.info(
                "resummarize: doc %s status=%s — skipping (expected 'processed')",
                document_id,
                doc.status,
            )
            return "skipped"

        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()

    text = "\n\n".join(r.text for r in rows) if rows else (doc.extracted_text or "")
    if not text.strip():
        log.info("resummarize: doc %s has no text — nothing to summarize", document_id)
        return "no-text"

    await _summarize_and_store(text=text, document_id=document_id)
    return "resummarized"


async def reindex_graph_for_document(ctx: dict[str, Any], document_id: str) -> str:
    # Re-run entity extraction on stored chunks. No re-OCR or re-embed.
    async with async_session_maker() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            log.warning("reindex_graph: doc %s not found", document_id)
            return "missing"

        if str(doc.status) != DocumentStatus.PROCESSED.value:
            log.info(
                "reindex_graph: doc %s status=%s — skipping (expected 'processed')",
                document_id,
                doc.status,
            )
            return "skipped"

        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()

    # Prefer stored chunk rows; fall back to extracted_text as a single
    # chunk for legacy docs indexed before chunking existed.
    if rows:
        chunk_texts = [r.text for r in rows]
    elif doc.extracted_text and doc.extracted_text.strip():
        chunk_texts = [doc.extracted_text]
    else:
        chunk_texts = []

    if not any(t.strip() for t in chunk_texts):
        log.info("reindex_graph: doc %s has no text — nothing to extract", document_id)
        return "no-text"

    await _ingest_graph(
        chunks=chunk_texts,
        user_id=str(doc.user_id),
        document_id=str(doc.id),
    )
    return "reindexed"


async def fetch_document(document_id: str) -> Document | None:
    # Test helper; not part of arq's surface.
    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()
