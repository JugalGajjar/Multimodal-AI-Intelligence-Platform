"""Business logic for document uploads."""

import asyncio
import contextlib
import io
import logging

from minio.error import S3Error
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.documents.models import Document, DocumentStatus
from app.storage.minio_client import (
    ensure_bucket,
    get_minio_client,
    object_storage_key,
)
from app.workers.queue import get_arq_pool

log = logging.getLogger("mmap.documents")


async def store_uploaded_file(
    *,
    db: AsyncSession,
    user_id,
    filename: str,
    content_type: str,
    data: bytes,
) -> Document:
    doc = Document(
        user_id=user_id,
        filename=filename,
        content_type=content_type.split(";", 1)[0].strip().lower(),
        size_bytes=len(data),
        storage_key="",
        status=DocumentStatus.UPLOADED,
    )
    db.add(doc)
    # Flush to populate doc.id without committing yet.
    await db.flush()

    key = object_storage_key(user_id, doc.id)
    try:
        await asyncio.to_thread(ensure_bucket, settings.minio_bucket)
        await asyncio.to_thread(
            get_minio_client().put_object,
            settings.minio_bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=doc.content_type,
        )
    except S3Error:
        await db.rollback()
        raise

    doc.storage_key = key
    await db.commit()
    await db.refresh(doc)

    await _enqueue_ocr(doc.id)
    return doc


async def _enqueue_ocr(document_id) -> None:
    # Worker outage shouldn't fail uploads — the doc will sit at "uploaded".
    try:
        pool = await get_arq_pool()
        try:
            await pool.enqueue_job("process_document_ocr", str(document_id))
        finally:
            await pool.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to enqueue OCR for %s: %s", document_id, exc)


async def enqueue_graph_reindex(document_id) -> bool:
    try:
        pool = await get_arq_pool()
        try:
            await pool.enqueue_job("reindex_graph_for_document", str(document_id))
        finally:
            await pool.close()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to enqueue graph reindex for %s: %s", document_id, exc)
        return False


async def enqueue_resummarize(document_id) -> bool:
    try:
        pool = await get_arq_pool()
        try:
            await pool.enqueue_job("resummarize_document", str(document_id))
        finally:
            await pool.close()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to enqueue resummarize for %s: %s", document_id, exc)
        return False


async def delete_stored_object(storage_key: str) -> None:
    # Best-effort: swallow not-found / bucket-missing.
    with contextlib.suppress(S3Error):
        await asyncio.to_thread(
            get_minio_client().remove_object,
            settings.minio_bucket,
            storage_key,
        )


async def delete_vector_points(document_id: str) -> None:
    # Postgres CASCADE has already removed chunk rows; Qdrant is best-effort.
    try:
        from app.storage.qdrant_client import delete_points_for_document

        await asyncio.to_thread(delete_points_for_document, document_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("qdrant cleanup failed for doc=%s: %s", document_id, exc)


async def delete_graph_traces(user_id: str, document_id: str) -> None:
    try:
        from app.graph.neo4j_client import delete_document_traces

        await delete_document_traces(user_id, document_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("graph cleanup failed for doc=%s: %s", document_id, exc)
