import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
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
from app.chats.service import (
    create_chat,
    delete_chat_row,
    get_owned_chat,
    load_history,
    persist_turn,
    refresh_chat_summary,
)
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
    # Validate request before checking provider availability — a 400 for bad
    # input shouldn't be masked by a 503 when the provider key is missing.
    if payload.chat_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chat_id is only supported on /chat/stream.",
        )

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


@dataclass
class _ChatCtx:
    chat_id: UUID
    created_now: bool
    is_first_turn: bool
    next_seq: int
    history: list[dict[str, str]] = field(default_factory=list)


async def _cleanup_failed_first_turn(chat_ctx: _ChatCtx) -> None:
    # Otherwise the empty chat lingers in the user's list.
    if chat_ctx.created_now:
        await delete_chat_row(chat_ctx.chat_id)


async def _stream_generator(
    payload: ChatRequest, user: User, chat_ctx: _ChatCtx
) -> AsyncIterator[bytes]:
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
            history=chat_ctx.history,
        )
    except GroqChatError as exc:
        yield _sse("error", {"status": exc.status_code, "detail": str(exc.body)})
        await _cleanup_failed_first_turn(chat_ctx)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("chat stream: prepare_context failed")
        yield _sse("error", {"status": 500, "detail": str(exc)})
        await _cleanup_failed_first_turn(chat_ctx)
        return

    chunks = state.get("chunks") or []
    graph_facts = state.get("graph_facts") or []
    web_results = state.get("web_results") or []

    intent = state.get("intent", "chat")
    citations_json = [c.model_dump(mode="json") for c in _citations_from_chunks(chunks)]
    entities_json = [e.model_dump() for e in _to_entities_used(graph_facts)]
    web_citations_json = [w.model_dump() for w in _web_citations(web_results)]

    yield _sse(
        "meta",
        {
            "chat_id": str(chat_ctx.chat_id),
            "intent": intent,
            "used_context": bool(state.get("used_context")),
            "used_graph": bool(state.get("used_graph")),
            "used_web": bool(state.get("used_web")),
            "model": settings.groq_reasoning_model,
            "citations": citations_json,
            "entities_used": entities_json,
            "web_citations": web_citations_json,
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
        await _cleanup_failed_first_turn(chat_ctx)
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("chat stream: token stream failed")
        yield _sse("error", {"status": 500, "detail": str(exc)})
        await _cleanup_failed_first_turn(chat_ctx)
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

    # After `done` — must never emit SSE or raise. Persist what the user
    # saw (the refusal, if gated). Summary in a separate commit.
    try:
        persisted_answer = refusal if refusal is not None else answer
        await persist_turn(
            chat_ctx.chat_id,
            question=payload.query,
            answer=persisted_answer,
            citations=citations_json,
            web_citations=web_citations_json,
            verification=_to_verification(verification).model_dump(),
            response_meta={
                "model": settings.groq_reasoning_model,
                "intent": intent,
                "used_context": bool(state.get("used_context")),
                "used_graph": bool(state.get("used_graph")),
                "used_web": bool(state.get("used_web")),
                "strict_refusal": refusal is not None,
                "entities_used": entities_json,
            },
            next_seq=chat_ctx.next_seq,
        )
        await refresh_chat_summary(
            chat_ctx.chat_id,
            turns=[
                *chat_ctx.history,
                {"role": "user", "content": payload.query},
                {"role": "assistant", "content": persisted_answer},
            ],
            generate_title=chat_ctx.is_first_turn,
        )
    except Exception:
        log.exception("chat stream: post-stream persistence failed")


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: CurrentUserDep,
    db: DbDep,
) -> StreamingResponse:
    _require_providers(payload)

    # Resolve chat + history before the stream so ownership 404s stay HTTP;
    # the generator never touches this session.
    if payload.chat_id is not None:
        chat = await get_owned_chat(db, payload.chat_id, current_user.id)
        if chat is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
        created_now = False
    else:
        chat = await create_chat(db, current_user.id, payload.query)
        created_now = True

    history, next_seq = await load_history(db, chat.id)
    chat_ctx = _ChatCtx(
        chat_id=chat.id,
        created_now=created_now,
        is_first_turn=next_seq == 0,
        next_seq=next_seq,
        history=history,
    )

    return StreamingResponse(
        _stream_generator(payload, current_user, chat_ctx),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
