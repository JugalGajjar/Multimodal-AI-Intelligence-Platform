"""arq tasks. Heavy ML imports live in app.workers.ocr.* (worker image only)."""

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_maker
from app.documents.models import Document, DocumentStatus
from app.storage.minio_client import get_minio_client

log = logging.getLogger("mmap.worker")


async def process_document_ocr(ctx: dict[str, Any], document_id: str) -> str:
    """Worker task: OCR a document and persist extracted text."""
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
            doc.status = DocumentStatus.PROCESSED
            await db.commit()
            log.info("ocr ok: doc=%s, %d chars extracted", document_id, len(text))
            return "processed"

        except Exception as exc:  # noqa: BLE001
            log.exception("ocr failed for doc=%s", document_id)
            doc.status = DocumentStatus.FAILED
            doc.extracted_text = f"OCR error: {exc}"
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


async def fetch_document(document_id: str) -> Document | None:
    """Test helper; not part of arq's surface."""
    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()
