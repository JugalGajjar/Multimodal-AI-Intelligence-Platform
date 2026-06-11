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
from app.agents.verification import VerificationResult, strict_refusal_for, verify_answer
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
    WebCitation,
)
from app.rag.tavily import WebResult

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


def _web_citations(results: list[WebResult]) -> list[WebCitation]:
    return [
        WebCitation(
            url=r.url,
            title=r.title,
            snippet=(r.content[:240] + "…") if len(r.content) > 240 else r.content,
            score=r.score,
        )
        for r in results
    ]


def _require_providers(payload: ChatRequest) -> None:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Groq API key not configured on the server",
        )
    # Missing key with the toggle ON is an explicit 503, not a silent no-op;
    # transient Tavily failures inside the workflow stay best-effort.
    if payload.use_web and not settings.tavily_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web search is not configured on the server (TAVILY_API_KEY missing)",
        )


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: CurrentUserDep,
    _db: DbDep,
) -> ChatResponse:
    _require_providers(payload)

    try:
        state = await run_chat(
            query=payload.query,
            user_id=current_user.id,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
            use_rag=payload.use_rag,
            use_web=payload.use_web,
            rag_mode=current_user.rag_mode,
            web_max_results=current_user.web_max_results,
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
        used_web=bool(state.get("used_web")),
        web_citations=_web_citations(state.get("web_results") or []),
        verification=_to_verification(state.get("verification")),
        strict_refusal=state.get("strict_refusal") is not None,
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
            use_rag=payload.use_rag,
            use_web=payload.use_web,
            rag_mode=user.rag_mode,
            web_max_results=user.web_max_results,
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
    web_results = state.get("web_results") or []

    yield _sse(
        "meta",
        {
            "intent": state.get("intent", "chat"),
            "used_context": bool(state.get("used_context")),
            "used_graph": bool(state.get("used_graph")),
            "used_web": bool(state.get("used_web")),
            "model": settings.groq_reasoning_model,
            "citations": [c.model_dump(mode="json") for c in _citations_from_chunks(chunks)],
            "entities_used": [e.model_dump() for e in _to_entities_used(graph_facts)],
            "web_citations": [w.model_dump() for w in _web_citations(web_results)],
            # Signals the client to buffer rendering until `done` decides
            # between the answer and a strict refusal.
            "strict": payload.use_rag and user.rag_mode == "strict",
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
        web_results=web_results,
    )
    refusal = strict_refusal_for(verification, rag_mode=user.rag_mode, use_rag=payload.use_rag)

    yield _sse(
        "done",
        {
            "verification": _to_verification(verification).model_dump(),
            "strict_refusal": refusal,
        },
    )


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: CurrentUserDep,
    _db: DbDep,
) -> StreamingResponse:
    _require_providers(payload)

    return StreamingResponse(
        _stream_generator(payload, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
