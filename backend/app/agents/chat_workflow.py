"""Phase 5.1 — LangGraph chat workflow.

A 2-node graph that wraps the prior inline `/chat` flow:

    START → retrieve → respond → END

Behaviour matches the previous router exactly; the only difference is that
state now flows through a LangGraph `StateGraph`, which gives subsequent
sub-phases (verification, summarization, routing) a clean insertion point.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

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
    """Mutable state threaded through the chat graph.

    `total=False` so node returns can be partial updates — LangGraph merges
    each node's return dict into the running state.
    """

    # Inputs
    query: str
    user_id: UUID
    top_k: int
    document_ids: list[UUID] | None

    # Filled by `retrieve`
    chunks: list[RetrievedChunk]
    graph_facts: list[GraphFact]
    used_context: bool
    used_graph: bool

    # Filled by `respond`
    answer: str
    model: str


async def _safe_expand(query: str, chunks, user_id) -> list[GraphFact]:
    """Graph expansion is best-effort. Neo4j down or empty graph → []."""
    try:
        return await expand_with_graph(query=query, chunks=chunks, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("graph expansion failed (non-blocking): %s", exc)
        return []


async def retrieve_node(state: ChatState) -> dict[str, Any]:
    """Run vector retrieval + best-effort graph expansion.

    Synchronously calls `retrieve` (CPU-bound embedding + Qdrant search) and
    awaits the async graph expansion. Returns a partial state update.
    """
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
    """Build the prompt from the retrieved state and call the LLM.

    Lets `GroqChatError` propagate so the FastAPI surface can map upstream
    status codes back to the client (rate-limits, missing key, etc.).
    """
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


def build_chat_workflow():
    """Compile and return the chat StateGraph.

    Safe to cache at module load — the compiled graph is stateless across
    invocations; per-request state lives in `ChatState`.
    """
    graph = StateGraph(ChatState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("respond", respond_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


# A single compiled graph reused across requests. Tests that need to swap the
# nodes (e.g. by patching `app.agents.chat_workflow.chat_completion`) work
# because the nodes resolve the patched symbols at call time, not compile time.
chat_workflow = build_chat_workflow()


async def run_chat(
    *,
    query: str,
    user_id: UUID,
    top_k: int = 5,
    document_ids: list[UUID] | None = None,
) -> ChatState:
    """Convenience entry point for the FastAPI router.

    Returns the final state dict containing answer, chunks, graph_facts, etc.
    """
    initial: ChatState = {
        "query": query,
        "user_id": user_id,
        "top_k": top_k,
        "document_ids": document_ids,
    }
    final = await chat_workflow.ainvoke(initial)
    return final  # type: ignore[return-value]
