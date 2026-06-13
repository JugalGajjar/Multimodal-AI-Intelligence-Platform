"""Chat persistence. Writes open their own session — they run after `done`
when the request session may already be closing."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_summary import summarize_chat
from app.chats.models import Chat, ChatMessage
from app.db.session import async_session_maker

log = logging.getLogger("mmap.chats")

HISTORY_MAX_MESSAGES = 10
HISTORY_MAX_CHARS = 8_000
HISTORY_PER_MESSAGE_CHARS = 2_000
PLACEHOLDER_TITLE_CHARS = 60


def _utcnow() -> datetime:
    return datetime.now(UTC)


def placeholder_title(first_query: str) -> str:
    text = " ".join(first_query.split())
    if len(text) <= PLACEHOLDER_TITLE_CHARS:
        return text or "New chat"
    cut = text[:PLACEHOLDER_TITLE_CHARS]
    # Trim to a word boundary if one's in the tail half.
    space = cut.rfind(" ")
    if space > PLACEHOLDER_TITLE_CHARS // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


async def get_owned_chat(db: AsyncSession, chat_id: UUID, user_id: UUID) -> Chat | None:
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.user_id != user_id:
        return None
    return chat


async def create_chat(db: AsyncSession, user_id: UUID, first_query: str) -> Chat:
    chat = Chat(user_id=user_id, title=placeholder_title(first_query))
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def load_history(
    db: AsyncSession,
    chat_id: UUID,
    *,
    max_messages: int = HISTORY_MAX_MESSAGES,
    max_chars: int = HISTORY_MAX_CHARS,
) -> tuple[list[dict[str, str]], int]:
    # next_seq is max seq + 1 (survives gaps), not row count.
    stmt = (
        select(ChatMessage.seq, ChatMessage.role, ChatMessage.content)
        .where(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.seq.desc())
        .limit(max_messages)
    )
    rows = list((await db.execute(stmt)).all())
    rows.reverse()

    next_seq = (rows[-1].seq + 1) if rows else 0

    history = [
        {
            "role": r.role,
            "content": (
                r.content
                if len(r.content) <= HISTORY_PER_MESSAGE_CHARS
                else r.content[:HISTORY_PER_MESSAGE_CHARS] + "…"
            ),
        }
        for r in rows
    ]
    while history and sum(len(m["content"]) for m in history) > max_chars:
        history.pop(0)
    return history, next_seq


async def persist_turn(
    chat_id: UUID,
    *,
    question: str,
    answer: str,
    citations: list[Any],
    web_citations: list[Any],
    verification: dict[str, Any],
    response_meta: dict[str, Any],
    next_seq: int,
) -> None:
    async with async_session_maker() as db:
        db.add(
            ChatMessage(
                chat_id=chat_id,
                seq=next_seq,
                role="user",
                content=question,
            )
        )
        db.add(
            ChatMessage(
                chat_id=chat_id,
                seq=next_seq + 1,
                role="assistant",
                content=answer,
                citations=citations,
                web_citations=web_citations,
                verification=verification,
                response_meta=response_meta,
            )
        )
        chat = await db.get(Chat, chat_id)
        if chat is not None:
            chat.updated_at = _utcnow()
        await db.commit()


async def refresh_chat_summary(
    chat_id: UUID,
    turns: list[dict[str, str]],
    *,
    generate_title: bool,
) -> None:
    # Best-effort — failure must not lose the messages persisted earlier.
    try:
        result = await summarize_chat(turns)
        if result.is_empty():
            return
        async with async_session_maker() as db:
            chat = await db.get(Chat, chat_id)
            if chat is None:
                return
            if result.summary:
                chat.summary = result.summary
            if generate_title and result.title:
                chat.title = result.title
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("chat summary refresh failed (non-blocking): %s", exc)


async def delete_chat_row(chat_id: UUID) -> None:
    # Used to clean up a chat whose first turn failed.
    try:
        async with async_session_maker() as db:
            chat = await db.get(Chat, chat_id)
            if chat is not None:
                await db.delete(chat)
                await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("chat cleanup failed (non-blocking): %s", exc)
