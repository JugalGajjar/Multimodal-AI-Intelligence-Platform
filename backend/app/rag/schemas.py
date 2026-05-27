from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[UUID] | None = None


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    score: float
    text_preview: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    model: str
    used_context: bool
