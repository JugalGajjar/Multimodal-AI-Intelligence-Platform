from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.rag.schemas import Citation, VerificationInfo, WebCitation


class ChatListItem(BaseModel):
    id: UUID
    title: str
    summary: str | None = None
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatListResponse(BaseModel):
    items: list[ChatListItem]
    total: int


class ChatMessageItem(BaseModel):
    id: UUID
    seq: int
    role: str
    content: str
    created_at: datetime
    citations: list[Citation] = []
    web_citations: list[WebCitation] = []
    verification: VerificationInfo | None = None
    response_meta: dict[str, Any] | None = None


class ChatDetailResponse(BaseModel):
    id: UUID
    title: str
    summary: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageItem]


class ChatRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatSearchItem(ChatListItem):
    snippet: str
    match_source: Literal["title", "summary", "message"]


class ChatSearchResponse(BaseModel):
    items: list[ChatSearchItem]
    total: int
    query: str
