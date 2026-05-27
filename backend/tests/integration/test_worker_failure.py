"""Worker FAILED-path test.

Calls process_document_ocr directly in-process against the live Postgres,
with the heavy ML deps patched out, to exercise the exception branch.

Asserts:
  - Task returns 'failed'
  - Document status flips to FAILED
  - No orphan chunks remain in Postgres (the pending db.add()s before the
    failing embed call must be rolled back).
"""

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import bcrypt
import pytest
from sqlalchemy import delete, select

from app.auth.models import User
from app.core.config import settings
from app.db.session import async_session_maker
from app.documents.chunks_model import DocumentChunk
from app.documents.models import Document, DocumentStatus
from app.storage.minio_client import ensure_bucket, get_minio_client
from app.workers.tasks import process_document_ocr

pytestmark = pytest.mark.integration


async def _create_test_user_and_doc(text_body: bytes) -> tuple[User, Document]:
    """Insert a user + document row + upload bytes to MinIO."""
    async with async_session_maker() as db:
        user = User(
            email=f"failtest-{uuid4().hex[:8]}@example.com",
            hashed_password=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        )
        db.add(user)
        await db.flush()

        doc = Document(
            user_id=user.id,
            filename="failtest.txt",
            content_type="text/plain",
            size_bytes=len(text_body),
            storage_key=f"users/{user.id}/documents/{uuid4()}",
            status=DocumentStatus.UPLOADED,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

    # Upload bytes so _download_bytes would work if called for real.
    ensure_bucket(settings.minio_bucket)
    get_minio_client().put_object(
        settings.minio_bucket,
        doc.storage_key,
        BytesIO(text_body),
        length=len(text_body),
        content_type="text/plain",
    )
    return user, doc


async def _read_doc(doc_id) -> Document:
    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        return result.scalar_one()


async def _count_chunks_for(doc_id) -> int:
    async with async_session_maker() as db:
        result = await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc_id))
        return len(result.scalars().all())


async def _cleanup(doc_id, user_id) -> None:
    async with async_session_maker() as db:
        await db.execute(delete(Document).where(Document.id == doc_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


async def test_failure_in_embedding_marks_doc_as_failed_with_no_orphan_chunks():
    text_body = ("This is a failure-path test. " * 30).encode()
    user, doc = await _create_test_user_and_doc(text_body)

    try:
        # Patch the imports the task does internally. Note: the task uses
        # `from app.embeddings import embed_texts` lazily inside the
        # function — patching the module attribute is what matters.
        with patch(
            "app.embeddings.embed_texts",
            side_effect=RuntimeError("simulated embedding failure"),
        ):
            result = await process_document_ocr({}, str(doc.id))

        assert result == "failed", f"expected 'failed', got {result!r}"

        refreshed = await _read_doc(doc.id)
        assert refreshed.status == DocumentStatus.FAILED
        assert refreshed.extracted_text is not None
        assert "Pipeline error" in refreshed.extracted_text

        # CRITICAL: no orphan chunks should remain in Postgres. They were
        # db.add()'d before embed_texts raised; the except branch must
        # rollback before persisting the FAILED status.
        chunk_count = await _count_chunks_for(doc.id)
        assert chunk_count == 0, f"expected 0 orphan chunks after failure, got {chunk_count}"

    finally:
        await _cleanup(doc.id, user.id)


async def test_failure_in_extract_text_marks_doc_as_failed():
    text_body = b"some content"
    user, doc = await _create_test_user_and_doc(text_body)

    try:
        with patch(
            "app.workers.ocr.pipeline.extract_text_from_bytes",
            side_effect=RuntimeError("simulated OCR failure"),
        ):
            result = await process_document_ocr({}, str(doc.id))

        assert result == "failed"

        refreshed = await _read_doc(doc.id)
        assert refreshed.status == DocumentStatus.FAILED
        assert await _count_chunks_for(doc.id) == 0

    finally:
        await _cleanup(doc.id, user.id)


async def test_missing_document_returns_missing():
    fake_id = uuid4()
    result = await process_document_ocr({}, str(fake_id))
    assert result == "missing"
