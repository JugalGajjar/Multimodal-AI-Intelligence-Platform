"""LangGraph chat workflow: retrieve → respond → verify."""

from __future__ import annotations

import logging
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agents.verification import VerificationResult, verify_answer
from app.core.config import settings
from app.rag.graph_expansion import GraphFact, expand_with_graph
from app.rag.groq_chat import chat_completion
from app.rag.prompts import (
    NO_CONTEXT_FALLBACK_SYSTEM,
    SYSTEM_PROMPT,
    build_user_message,
)
from app.rag.retrieval import RetrievedChunk, retrieve

log = logging.getLogger("mmap.agents.chat")


class ChatState(TypedDict, total=False):
    # total=False lets each node return a partial update; LangGraph merges them.
    query: str
    user_id: UUID
    top_k: int
    document_ids: list[UUID] | None

    chunks: list[RetrievedChunk]
    graph_facts: list[GraphFact]
    used_context: bool
    used_graph: bool

    answer: str
    model: str

    verification: VerificationResult


async def _safe_expand(query: str, chunks, user_id) -> list[GraphFact]:
    # Graph expansion is best-effort; Neo4j down should not break chat.
    try:
        return await expand_with_graph(query=query, chunks=chunks, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("graph expansion failed (non-blocking): %s", exc)
        return []


async def retrieve_node(state: ChatState) -> dict[str, Any]:
    chunks = retrieve(
        query=state["query"],
        user_id=state["user_id"],
        top_k=state.get("top_k", 5),
        document_ids=state.get("document_ids"),
    )
    graph_facts = await _safe_expand(state["query"], chunks, state["user_id"])

    return {
        "chunks": chunks,
        "graph_facts": graph_facts,
        "used_context": bool(chunks),
        "used_graph": bool(graph_facts),
    }


async def respond_node(state: ChatState) -> dict[str, Any]:
    # Lets GroqChatError propagate so the router can map upstream status codes.
    chunks = state.get("chunks") or []
    graph_facts = state.get("graph_facts") or []

    system = SYSTEM_PROMPT if (chunks or graph_facts) else NO_CONTEXT_FALLBACK_SYSTEM
    user_msg = build_user_message(state["query"], chunks, facts=graph_facts)

    answer = await chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )

    return {
        "answer": answer,
        "model": settings.groq_reasoning_model,
    }


async def verify_node(state: ChatState) -> dict[str, Any]:
    # verify_answer maps every failure mode to a `skipped` verdict, so the
    # chat response never fails because of verification.
    result = await verify_answer(
        answer=state.get("answer", ""),
        chunks=state.get("chunks") or [],
        graph_facts=state.get("graph_facts") or [],
    )
    return {"verification": result}


def build_chat_workflow():
    graph = StateGraph(ChatState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("respond", respond_node)
    graph.add_node("verify", verify_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


# Compiled once at import. Tests patch module-level symbols (chat_completion,
# verify_answer, etc.); nodes resolve them at call time so patches still hit.
chat_workflow = build_chat_workflow()


async def run_chat(
    *,
    query: str,
    user_id: UUID,
    top_k: int = 5,
    document_ids: list[UUID] | None = None,
) -> ChatState:
    initial: ChatState = {
        "query": query,
        "user_id": user_id,
        "top_k": top_k,
        "document_ids": document_ids,
    }
    final = await chat_workflow.ainvoke(initial)
    return final  # type: ignore[return-value]
