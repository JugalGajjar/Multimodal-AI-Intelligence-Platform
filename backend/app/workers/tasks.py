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
    """Worker task: OCR → chunk → embed → upsert into Qdrant."""
    from app.embeddings import embed_texts
    from app.workers.chunking import chunk_text
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
            text = await asyncio.to_thread(extract_text_from_bytes, data, doc.content_type)
            doc.extracted_text = text

            chunks = chunk_text(text) if text.strip() else []
            log.info("doc=%s ocr=%d chars chunks=%d", document_id, len(text), len(chunks))

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
            return "processed"

        except Exception as exc:  # noqa: BLE001
            log.exception("ocr pipeline failed for doc=%s", document_id)
            # Discard any pending chunk inserts (added before embed/upsert
            # ran). Without this, db.commit() below would persist orphan
            # chunks with no matching Qdrant points.
            await db.rollback()
            failed_doc = await db.get(Document, document_id)
            if failed_doc is not None:
                failed_doc.status = DocumentStatus.FAILED
                failed_doc.extracted_text = f"Pipeline error: {exc}"
                await db.commit()
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
    """Idempotent upsert into the chunks collection."""
    from qdrant_client.http import models as qmodels

    from app.storage.qdrant_client import (
        COLLECTION_NAME,
        ensure_collection,
        get_qdrant_client,
    )

    ensure_collection()
    client = get_qdrant_client()

    points = [
        qmodels.PointStruct(
            id=str(row.id),
            vector=vec,
            payload={
                "chunk_id": str(row.id),
                "document_id": document_id,
                "user_id": user_id,
                "chunk_index": row.chunk_index,
                "text": row.text,
            },
        )
        for row, vec in zip(chunk_rows, vectors, strict=True)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)


async def fetch_document(document_id: str) -> Document | None:
    """Test helper; not part of arq's surface."""
    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()
