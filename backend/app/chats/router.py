"""Chat history endpoints: list, search, transcript, rename, delete."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.chats.models import Chat, ChatMessage
from app.chats.schemas import (
    ChatDetailResponse,
    ChatListItem,
    ChatListResponse,
    ChatMessageItem,
    ChatRenameRequest,
    ChatSearchItem,
    ChatSearchResponse,
)
from app.chats.service import get_owned_chat
from app.db.session import get_db
from app.rag.schemas import VerificationInfo

log = logging.getLogger("mmap.chats")

router = APIRouter(prefix="/chats", tags=["chats"])

CurrentUserDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]

SNIPPET_WIDTH = 160


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(text: str, q: str, *, width: int = SNIPPET_WIDTH) -> str:
    """Window of `width` chars centered on the first case-insensitive match."""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[:width].rstrip() + "…"
    start = max(0, idx + len(q) // 2 - width // 2)
    end = min(len(text), start + width)
    start = max(0, end - width)
    out = text[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _list_item(chat: Chat, message_count: int) -> ChatListItem:
    return ChatListItem(
        id=chat.id,
        title=chat.title,
        summary=chat.summary,
        message_count=message_count,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


@router.get("", response_model=ChatListResponse)
async def list_chats(current_user: CurrentUserDep, db: DbDep) -> ChatListResponse:
    # Message bodies never loaded — counts only.
    stmt = (
        select(Chat, func.count(ChatMessage.id))
        .outerjoin(ChatMessage, ChatMessage.chat_id == Chat.id)
        .where(Chat.user_id == current_user.id)
        .group_by(Chat.id)
        .order_by(Chat.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    items = [_list_item(chat, count) for chat, count in rows]
    return ChatListResponse(items=items, total=len(items))


# Must be declared before /{chat_id} or FastAPI binds "search" as the UUID.
@router.get("/search", response_model=ChatSearchResponse)
async def search_chats(
    current_user: CurrentUserDep,
    db: DbDep,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> ChatSearchResponse:
    pat = f"%{_escape_like(q)}%"

    meta_stmt = select(Chat).where(
        Chat.user_id == current_user.id,
        Chat.title.ilike(pat) | Chat.summary.ilike(pat),
    )
    meta_chats = (await db.execute(meta_stmt)).scalars().all()

    # DISTINCT ON gives us the first matching message per chat in the DB,
    # no Python dedup needed.
    msg_stmt = (
        select(ChatMessage.chat_id, ChatMessage.content)
        .join(Chat, Chat.id == ChatMessage.chat_id)
        .where(Chat.user_id == current_user.id, ChatMessage.content.ilike(pat))
        .distinct(ChatMessage.chat_id)
        .order_by(ChatMessage.chat_id, ChatMessage.seq.asc())
    )
    msg_rows = (await db.execute(msg_stmt)).all()
    msg_match: dict[UUID, str] = {chat_id: content for chat_id, content in msg_rows}

    # Match-source priority: title > summary > message.
    merged: dict[UUID, tuple[Chat | None, str, str]] = {}
    for chat in meta_chats:
        if q.lower() in chat.title.lower():
            merged[chat.id] = (chat, chat.title, "title")
        else:
            merged[chat.id] = (chat, chat.summary or "", "summary")
    for chat_id, content in msg_match.items():
        if chat_id not in merged:
            merged[chat_id] = (None, content, "message")

    if not merged:
        return ChatSearchResponse(items=[], total=0, query=q)

    ids = list(merged.keys())
    rows_stmt = (
        select(Chat, func.count(ChatMessage.id))
        .outerjoin(ChatMessage, ChatMessage.chat_id == Chat.id)
        .where(Chat.id.in_(ids), Chat.user_id == current_user.id)
        .group_by(Chat.id)
        .order_by(Chat.updated_at.desc())
    )
    rows = (await db.execute(rows_stmt)).all()

    items: list[ChatSearchItem] = []
    for chat, count in rows[:limit]:
        _, matched_text, source = merged[chat.id]
        items.append(
            ChatSearchItem(
                **_list_item(chat, count).model_dump(),
                snippet=_snippet(matched_text, q),
                match_source=source,  # type: ignore[arg-type]
            )
        )
    return ChatSearchResponse(items=items, total=len(items), query=q)


@router.get("/{chat_id}", response_model=ChatDetailResponse)
async def get_chat(chat_id: UUID, current_user: CurrentUserDep, db: DbDep) -> ChatDetailResponse:
    chat = await get_owned_chat(db, chat_id, current_user.id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    stmt = select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.seq.asc())
    messages = (await db.execute(stmt)).scalars().all()

    return ChatDetailResponse(
        id=chat.id,
        title=chat.title,
        summary=chat.summary,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[
            ChatMessageItem(
                id=m.id,
                seq=m.seq,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                citations=m.citations or [],
                web_citations=m.web_citations or [],
                verification=(
                    VerificationInfo.model_validate(m.verification) if m.verification else None
                ),
                response_meta=m.response_meta,
            )
            for m in messages
        ],
    )


@router.patch("/{chat_id}", response_model=ChatListItem)
async def rename_chat(
    chat_id: UUID,
    payload: ChatRenameRequest,
    current_user: CurrentUserDep,
    db: DbDep,
) -> ChatListItem:
    chat = await get_owned_chat(db, chat_id, current_user.id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    chat.title = payload.title.strip()
    await db.commit()
    await db.refresh(chat)

    count_stmt = select(func.count(ChatMessage.id)).where(ChatMessage.chat_id == chat.id)
    count = (await db.execute(count_stmt)).scalar_one()
    return _list_item(chat, count)


@router.delete(
    "/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Not found"}},
)
async def delete_chat(chat_id: UUID, current_user: CurrentUserDep, db: DbDep) -> None:
    chat = await get_owned_chat(db, chat_id, current_user.id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    # Messages cascade via FK ON DELETE.
    await db.delete(chat)
    await db.commit()
