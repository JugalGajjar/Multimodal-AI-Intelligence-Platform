"""LangGraph chat workflow with intent routing.

START → classify → ┬→ retrieve_for_chat
                   ├→ fetch_summaries
                   └→ retrieve_for_graph
                        → respond → verify → END
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agents.intent_router import DEFAULT_INTENT, Intent, classify_intent
from app.agents.verification import VerificationResult, verify_answer
from app.core.config import settings
from app.core.metrics import time_node_async
from app.documents.service import list_summaries_for_user
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

    intent: Intent
    chunks: list[RetrievedChunk]
    graph_facts: list[GraphFact]
    doc_summaries: list[dict[str, Any]]
    used_context: bool
    used_graph: bool

    answer: str
    model: str

    verification: VerificationResult


async def _safe_expand(query: str, chunks, user_id, *, max_hops=None) -> list[GraphFact]:
    # Graph expansion is best-effort; Neo4j down should not break chat.
    try:
        return await expand_with_graph(
            query=query, chunks=chunks, user_id=user_id, max_hops=max_hops
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("graph expansion failed (non-blocking): %s", exc)
        return []


async def classify_node(state: ChatState) -> dict[str, Any]:
    async with time_node_async("classify"):
        intent = await classify_intent(state["query"])
    return {"intent": intent}


async def retrieve_for_chat_node(state: ChatState) -> dict[str, Any]:
    async with time_node_async("retrieve_for_chat"):
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


async def fetch_summaries_node(state: ChatState) -> dict[str, Any]:
    async with time_node_async("fetch_summaries"):
        summaries = await list_summaries_for_user(
            state["user_id"], limit=settings.router_max_summary_docs
        )
    return {
        "doc_summaries": summaries,
        "chunks": [],
        "graph_facts": [],
        "used_context": bool(summaries),
        "used_graph": False,
    }


async def retrieve_for_graph_node(state: ChatState) -> dict[str, Any]:
    # Graph-only path: no vector chunks, broader graph walk for richer context.
    async with time_node_async("retrieve_for_graph"):
        chunks: list[RetrievedChunk] = []
        graph_facts = await _safe_expand(
            state["query"], chunks, state["user_id"], max_hops=settings.graph_max_hops
        )

    return {
        "chunks": chunks,
        "graph_facts": graph_facts,
        "used_context": False,
        "used_graph": bool(graph_facts),
    }


def _route_after_classify(state: ChatState) -> str:
    intent = state.get("intent") or DEFAULT_INTENT
    if intent == "summarize":
        return "fetch_summaries"
    if intent == "explain_graph":
        return "retrieve_for_graph"
    return "retrieve_for_chat"


def build_respond_messages(state: ChatState) -> list[dict[str, str]]:
    """Assemble the system + user messages for the respond call.

    Exposed so the streaming endpoint can build the exact same prompt the
    non-streaming path uses.
    """
    chunks = state.get("chunks") or []
    graph_facts = state.get("graph_facts") or []
    summaries = state.get("doc_summaries") or []

    has_context = bool(chunks or graph_facts or summaries)
    system = SYSTEM_PROMPT if has_context else NO_CONTEXT_FALLBACK_SYSTEM
    user_msg = build_user_message(state["query"], chunks, facts=graph_facts, summaries=summaries)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]


async def respond_node(state: ChatState) -> dict[str, Any]:
    # Lets GroqChatError propagate so the router can map upstream status codes.
    async with time_node_async("respond"):
        answer = await chat_completion(messages=build_respond_messages(state))
    return {
        "answer": answer,
        "model": settings.groq_reasoning_model,
    }


async def prepare_context_state(
    *,
    query: str,
    user_id: UUID,
    top_k: int = 5,
    document_ids: list[UUID] | None = None,
) -> ChatState:
    """Run classify + the appropriate retrieve branch, returning a populated
    state ready for either `respond_node` or a streaming completion."""
    state: ChatState = {
        "query": query,
        "user_id": user_id,
        "top_k": top_k,
        "document_ids": document_ids,
    }
    intent = await classify_intent(query)
    state["intent"] = intent

    if intent == "summarize":
        state.update(await fetch_summaries_node(state))  # type: ignore[typeddict-item]
    elif intent == "explain_graph":
        state.update(await retrieve_for_graph_node(state))  # type: ignore[typeddict-item]
    else:
        state.update(await retrieve_for_chat_node(state))  # type: ignore[typeddict-item]

    return state


async def verify_node(state: ChatState) -> dict[str, Any]:
    # verify_answer maps every failure mode to a `skipped` verdict, so the
    # chat response never fails because of verification.
    async with time_node_async("verify"):
        result = await verify_answer(
            answer=state.get("answer", ""),
            chunks=state.get("chunks") or [],
            graph_facts=state.get("graph_facts") or [],
        )
    return {"verification": result}


def build_chat_workflow():
    graph = StateGraph(ChatState)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve_for_chat", retrieve_for_chat_node)
    graph.add_node("fetch_summaries", fetch_summaries_node)
    graph.add_node("retrieve_for_graph", retrieve_for_graph_node)
    graph.add_node("respond", respond_node)
    graph.add_node("verify", verify_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {
            "retrieve_for_chat": "retrieve_for_chat",
            "fetch_summaries": "fetch_summaries",
            "retrieve_for_graph": "retrieve_for_graph",
        },
    )
    graph.add_edge("retrieve_for_chat", "respond")
    graph.add_edge("fetch_summaries", "respond")
    graph.add_edge("retrieve_for_graph", "respond")
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
