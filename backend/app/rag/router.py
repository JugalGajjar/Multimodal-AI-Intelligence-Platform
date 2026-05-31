import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_workflow import run_chat
from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import settings
from app.db.session import get_db
from app.rag.graph_expansion import GraphFact
from app.rag.groq_chat import GroqChatError
from app.rag.schemas import (
    ChatRequest,
    ChatResponse,
    Citation,
    EntityUsed,
    GraphRelationEdge,
)

log = logging.getLogger("mmap.rag")

router = APIRouter(prefix="/chat", tags=["chat"])

CurrentUserDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def _to_entities_used(facts: list[GraphFact]) -> list[EntityUsed]:
    return [
        EntityUsed(
            name=f.name,
            type=f.type,
            description=f.description,
            relations=[
                GraphRelationEdge(
                    relation=r.relation,
                    other=r.other,
                    other_type=r.other_type,
                    other_description=r.other_description,
                    distance=r.distance,
                    relation_chain=list(r.relation_chain),
                )
                for r in f.relations
            ],
        )
        for f in facts
    ]


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

    try:
        state = await run_chat(
            query=payload.query,
            user_id=current_user.id,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
    except GroqChatError as exc:
        code = exc.status_code if 400 <= exc.status_code < 600 else 502
        raise HTTPException(status_code=code, detail=str(exc.body)) from exc

    chunks = state.get("chunks") or []
    graph_facts = state.get("graph_facts") or []

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
        answer=state.get("answer", ""),
        citations=citations,
        entities_used=_to_entities_used(graph_facts),
        model=state.get("model", settings.groq_reasoning_model),
        used_context=bool(state.get("used_context")),
        used_graph=bool(state.get("used_graph")),
    )
