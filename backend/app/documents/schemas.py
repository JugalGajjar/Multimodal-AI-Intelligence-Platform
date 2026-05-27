from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.documents.models import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentTextResponse(BaseModel):
    id: UUID
    status: DocumentStatus
    extracted_text: str | None


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chunk_index: int
    text: str
    char_start: int
    char_end: int


class ChunkListResponse(BaseModel):
    document_id: UUID
    total: int
    items: list[ChunkResponse]
