import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.chat_workflow import (
    build_respond_messages,
    prepare_context_state,
    run_chat,
)
from app.agents.verification import VerificationResult, verify_answer
from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import settings
from app.db.session import get_db
from app.rag.graph_expansion import GraphFact
from app.rag.groq_chat import GroqChatError, stream_chat_completion
from app.rag.schemas import (
    ChatRequest,
    ChatResponse,
    Citation,
    EntityUsed,
    GraphRelationEdge,
    VerificationInfo,
)

log = logging.getLogger("mmap.rag")

router = APIRouter(prefix="/chat", tags=["chat"])

CurrentUserDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def _to_verification(result: VerificationResult | None) -> VerificationInfo:
    if result is None:
        return VerificationInfo(verdict="skipped", skip_reason="not run")
    return VerificationInfo(
        verdict=result.verdict,
        groundedness_score=round(result.groundedness_score, 3),
        total_claims=result.total_claims,
        supported_claims=result.supported_claims,
        unsupported_claims=list(result.unsupported_claims),
        skip_reason=result.skip_reason,
    )


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


def _citations_from_chunks(chunks: list) -> list[Citation]:
    return [
        Citation(
            chunk_id=UUID(c.chunk_id),
            document_id=UUID(c.document_id),
            chunk_index=c.chunk_index,
            score=c.score,
            text_preview=(c.text[:240] + "…") if len(c.text) > 240 else c.text,
        )
        for c in chunks
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

    return ChatResponse(
        answer=state.get("answer", ""),
        citations=_citations_from_chunks(chunks),
        entities_used=_to_entities_used(graph_facts),
        model=state.get("model", settings.groq_reasoning_model),
        used_context=bool(state.get("used_context")),
        used_graph=bool(state.get("used_graph")),
        verification=_to_verification(state.get("verification")),
        intent=state.get("intent", "chat"),
    )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def _stream_generator(payload: ChatRequest, user: User) -> AsyncIterator[bytes]:
    try:
        state = await prepare_context_state(
            query=payload.query,
            user_id=user.id,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
    except GroqChatError as exc:
        yield _sse("error", {"status": exc.status_code, "detail": str(exc.body)})
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("chat stream: prepare_context failed")
        yield _sse("error", {"status": 500, "detail": str(exc)})
        return

    chunks = state.get("chunks") or []
    graph_facts = state.get("graph_facts") or []

    yield _sse(
        "meta",
        {
            "intent": state.get("intent", "chat"),
            "used_context": bool(state.get("used_context")),
            "used_graph": bool(state.get("used_graph")),
            "model": settings.groq_reasoning_model,
            "citations": [c.model_dump(mode="json") for c in _citations_from_chunks(chunks)],
            "entities_used": [e.model_dump() for e in _to_entities_used(graph_facts)],
        },
    )

    parts: list[str] = []
    try:
        async for token in stream_chat_completion(messages=build_respond_messages(state)):
            parts.append(token)
            yield _sse("token", {"text": token})
    except GroqChatError as exc:
        yield _sse("error", {"status": exc.status_code, "detail": str(exc.body)})
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("chat stream: token stream failed")
        yield _sse("error", {"status": 500, "detail": str(exc)})
        return

    answer = "".join(parts)
    verification = await verify_answer(
        answer=answer,
        chunks=chunks,
        graph_facts=graph_facts,
    )

    yield _sse(
        "done",
        {
            "verification": _to_verification(verification).model_dump(),
        },
    )


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: CurrentUserDep,
    _db: DbDep,
) -> StreamingResponse:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Groq API key not configured on the server",
        )

    return StreamingResponse(
        _stream_generator(payload, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
