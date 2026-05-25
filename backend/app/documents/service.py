"""Business logic for document uploads."""

import asyncio
import contextlib
import io

from minio.error import S3Error
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.documents.models import Document, DocumentStatus
from app.storage.minio_client import (
    ensure_bucket,
    get_minio_client,
    object_storage_key,
)


async def store_uploaded_file(
    *,
    db: AsyncSession,
    user_id,
    filename: str,
    content_type: str,
    data: bytes,
) -> Document:
    """Create the DB row + push bytes to MinIO. All-or-nothing."""
    doc = Document(
        user_id=user_id,
        filename=filename,
        content_type=content_type.split(";", 1)[0].strip().lower(),
        size_bytes=len(data),
        storage_key="",
        status=DocumentStatus.UPLOADED,
    )
    db.add(doc)
    await db.flush()  # populates doc.id without committing

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
    return doc


async def delete_stored_object(storage_key: str) -> None:
    """Best-effort MinIO delete; swallow not-found / bucket-missing."""
    with contextlib.suppress(S3Error):
        await asyncio.to_thread(
            get_minio_client().remove_object,
            settings.minio_bucket,
            storage_key,
        )
