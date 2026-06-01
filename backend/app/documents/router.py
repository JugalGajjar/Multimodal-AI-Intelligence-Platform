from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.db.session import get_db
from app.documents.chunks_model import DocumentChunk
from app.documents.models import Document
from app.documents.schemas import (
    ChunkListResponse,
    ChunkResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentTextResponse,
)
from app.documents.service import (
    delete_graph_traces,
    delete_stored_object,
    delete_vector_points,
    enqueue_graph_reindex,
    enqueue_resummarize,
    store_uploaded_file,
)
from app.documents.validation import (
    MAX_FILE_SIZE_BYTES,
    is_allowed_mime,
    sanitize_filename,
)

router = APIRouter(prefix="/documents", tags=["documents"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    current_user: CurrentUserDep,
    db: DbDep,
    file: UploadFile = File(...),  # noqa: B008  (FastAPI marker)
) -> Document:
    if not is_allowed_mime(file.content_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type!r}",
        )

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES} bytes",
        )

    return await store_uploaded_file(
        db=db,
        user_id=current_user.id,
        filename=sanitize_filename(file.filename),
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(current_user: CurrentUserDep, db: DbDep) -> DocumentListResponse:
    stmt = (
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    count_stmt = (
        select(func.count()).select_from(Document).where(Document.user_id == current_user.id)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in items],
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: UUID, current_user: CurrentUserDep, db: DbDep) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
async def list_document_chunks(
    document_id: UUID, current_user: CurrentUserDep, db: DbDep
) -> ChunkListResponse:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()

    return ChunkListResponse(
        document_id=document_id,
        total=len(chunks),
        items=[ChunkResponse.model_validate(c) for c in chunks],
    )


@router.get("/{document_id}/text", response_model=DocumentTextResponse)
async def get_document_text(
    document_id: UUID, current_user: CurrentUserDep, db: DbDep
) -> DocumentTextResponse:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentTextResponse(id=doc.id, status=doc.status, extracted_text=doc.extracted_text)


@router.post(
    "/{document_id}/reindex-graph",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "Not found"},
        409: {"description": "Document not yet processed"},
        503: {"description": "Background queue unavailable"},
    },
)
async def reindex_document_graph(
    document_id: UUID, current_user: CurrentUserDep, db: DbDep
) -> dict:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Status is a StrEnum typed as a String column; coerce so == "processed" is reliable.
    if str(doc.status) != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document status is '{doc.status}'; only processed documents can be reindexed",
        )

    queued = await enqueue_graph_reindex(doc.id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background queue unavailable; please retry shortly",
        )
    return {"queued": True, "document_id": str(doc.id)}


@router.post(
    "/{document_id}/resummarize",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "Not found"},
        409: {"description": "Document not yet processed"},
        503: {"description": "Background queue unavailable"},
    },
)
async def resummarize_document_endpoint(
    document_id: UUID, current_user: CurrentUserDep, db: DbDep
) -> dict:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if str(doc.status) != "processed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document status is '{doc.status}'; only processed documents can be summarized",
        )

    queued = await enqueue_resummarize(doc.id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background queue unavailable; please retry shortly",
        )
    return {"queued": True, "document_id": str(doc.id)}


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Not found"}},
)
async def delete_document(document_id: UUID, current_user: CurrentUserDep, db: DbDep) -> None:
    doc = await db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage_key = doc.storage_key
    doc_id_str = str(doc.id)
    user_id_str = str(doc.user_id)
    await db.delete(doc)
    await db.commit()

    if storage_key:
        await delete_stored_object(storage_key)
    await delete_vector_points(doc_id_str)
    await delete_graph_traces(user_id_str, doc_id_str)
