from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import settings
from app.db.session import get_db
from app.rag.groq_chat import GroqChatError, chat_completion
from app.rag.prompts import (
    NO_CONTEXT_FALLBACK_SYSTEM,
    SYSTEM_PROMPT,
    build_user_message,
)
from app.rag.retrieval import retrieve
from app.rag.schemas import ChatRequest, ChatResponse, Citation

router = APIRouter(prefix="/chat", tags=["chat"])

CurrentUserDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: CurrentUserDep,
    _db: DbDep,
) -> ChatResponse:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Groq API key not configured on the server",
        )

    chunks = retrieve(
        query=payload.query,
        user_id=current_user.id,
        top_k=payload.top_k,
        document_ids=payload.document_ids,
    )

    system = SYSTEM_PROMPT if chunks else NO_CONTEXT_FALLBACK_SYSTEM
    user_msg = build_user_message(payload.query, chunks)

    try:
        answer = await chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
        )
    except GroqChatError as exc:
        # Surface upstream failures rather than 500-ing.
        code = exc.status_code if 400 <= exc.status_code < 600 else 502
        raise HTTPException(status_code=code, detail=str(exc.body)) from exc

    citations = [
        Citation(
            chunk_id=UUID(c.chunk_id),
            document_id=UUID(c.document_id),
            chunk_index=c.chunk_index,
            score=c.score,
            text_preview=(c.text[:240] + "…") if len(c.text) > 240 else c.text,
        )
        for c in chunks
    ]

    return ChatResponse(
        answer=answer,
        citations=citations,
        model=settings.groq_reasoning_model,
        used_context=bool(chunks),
    )
