"""LangGraph chat workflow with intent routing.

START → classify → ┬→ retrieve_for_chat ─┐
                   ├→ fetch_summaries    ├→ web_search → respond → verify
                   ├→ retrieve_for_graph ┤                           ↓
                   └→ skip_retrieval ────┘              strict_gate → END

`skip_retrieval` is the RAG-off path; `web_search` self-no-ops unless the
request asked for web augmentation; `strict_gate` replaces low-groundedness
answers with a refusal in strict mode.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agents.intent_router import DEFAULT_INTENT, Intent, classify_intent
from app.agents.verification import VerificationResult, strict_refusal_for, verify_answer
from app.core.config import settings
from app.core.metrics import time_node_async
from app.documents.service import list_summaries_for_user
from app.rag.graph_expansion import GraphFact, expand_with_graph
from app.rag.groq_chat import chat_completion
from app.rag.prompts import (
    NO_CONTEXT_FALLBACK_SYSTEM,
    PURE_KNOWLEDGE_SYSTEM,
    REGULAR_MODE_SYSTEM,
    SYSTEM_PROMPT,
    WEB_ONLY_SYSTEM,
    build_user_message,
)
from app.rag.retrieval import RetrievedChunk, retrieve
from app.rag.tavily import WebResult, search_web

log = logging.getLogger("mmap.agents.chat")


class ChatState(TypedDict, total=False):
    # total=False lets each node return a partial update; LangGraph merges them.
    query: str
    user_id: UUID
    top_k: int
    document_ids: list[UUID] | None
    use_rag: bool  # default True at entry points
    use_web: bool  # default False
    rag_mode: str  # "strict" | "regular", from the user row
    web_max_results: int
    # Answer-model override. None = fall back to settings.groq_reasoning_model.
    chat_model: str | None
    # Past turns ([{role, content}]) — fed to respond only.
    history: list[dict[str, str]]

    intent: Intent
    chunks: list[RetrievedChunk]
    graph_facts: list[GraphFact]
    doc_summaries: list[dict[str, Any]]
    web_results: list[WebResult]
    used_context: bool
    used_graph: bool
    used_web: bool

    answer: str
    model: str

    verification: VerificationResult
    strict_refusal: str | None


async def _safe_expand(query: str, chunks, user_id, *, max_hops=None) -> list[GraphFact]:
    # Graph expansion is best-effort; Neo4j down should not break chat.
    try:
        return await expand_with_graph(
            query=query, chunks=chunks, user_id=user_id, max_hops=max_hops
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("graph expansion failed (non-blocking): %s", exc)
        return []


async def _safe_web_search(query: str, max_results: int) -> list[WebResult]:
    # Web search is best-effort; a transient Tavily failure should not break
    # chat. The hard "key not configured" case is rejected at the router.
    try:
        return await search_web(query=query, max_results=max_results)
    except Exception as exc:  # noqa: BLE001
        log.warning("web search failed (non-blocking): %s", exc)
        return []


async def classify_node(state: ChatState) -> dict[str, Any]:
    # RAG off → no retrieval branches apply, so skip the classifier's Groq
    # call entirely and take the default intent.
    if not state.get("use_rag", True):
        return {"intent": DEFAULT_INTENT}
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


async def skip_retrieval_node(state: ChatState) -> dict[str, Any]:
    # RAG-off path: no document context at all.
    return {
        "chunks": [],
        "graph_facts": [],
        "doc_summaries": [],
        "used_context": False,
        "used_graph": False,
    }


async def web_search_node(state: ChatState) -> dict[str, Any]:
    if not state.get("use_web", False):
        return {"web_results": [], "used_web": False}
    async with time_node_async("web_search"):
        results = await _safe_web_search(state["query"], state.get("web_max_results", 5))
    return {"web_results": results, "used_web": bool(results)}


def _route_after_classify(state: ChatState) -> str:
    if not state.get("use_rag", True):
        return "skip_retrieval"
    intent = state.get("intent") or DEFAULT_INTENT
    if intent == "summarize":
        return "fetch_summaries"
    if intent == "explain_graph":
        return "retrieve_for_graph"
    return "retrieve_for_chat"


def _select_system_prompt(
    *,
    use_rag: bool,
    rag_mode: str,
    has_doc_context: bool,
    has_web: bool,
) -> str:
    if use_rag and has_doc_context:
        return SYSTEM_PROMPT if rag_mode == "strict" else REGULAR_MODE_SYSTEM
    if has_web:
        return WEB_ONLY_SYSTEM
    if use_rag:
        # RAG on but nothing retrieved and no web: strict keeps the upload
        # nag (it declines, verifier skips, gate fails open — coherent);
        # regular falls back to model knowledge.
        return NO_CONTEXT_FALLBACK_SYSTEM if rag_mode == "strict" else PURE_KNOWLEDGE_SYSTEM
    return PURE_KNOWLEDGE_SYSTEM


def build_respond_messages(state: ChatState) -> list[dict[str, str]]:
    """Assemble the system + user messages for the respond call.

    Exposed so the streaming endpoint can build the exact same prompt the
    non-streaming path uses.
    """
    chunks = state.get("chunks") or []
    graph_facts = state.get("graph_facts") or []
    summaries = state.get("doc_summaries") or []
    web_results = state.get("web_results") or []

    system = _select_system_prompt(
        use_rag=state.get("use_rag", True),
        rag_mode=state.get("rag_mode", "strict"),
        has_doc_context=bool(chunks or graph_facts or summaries),
        has_web=bool(web_results),
    )
    user_msg = build_user_message(
        state["query"],
        chunks,
        facts=graph_facts,
        summaries=summaries,
        web_results=web_results,
    )
    # History sits between system and the current (context-laden) user msg.
    history = state.get("history") or []
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_msg},
    ]


async def respond_node(state: ChatState) -> dict[str, Any]:
    # Lets GroqChatError propagate so the router can map upstream status codes.
    model = state.get("chat_model") or settings.groq_reasoning_model
    async with time_node_async("respond"):
        answer = await chat_completion(messages=build_respond_messages(state), model=model)
    return {
        "answer": answer,
        "model": model,
    }


async def prepare_context_state(
    *,
    query: str,
    user_id: UUID,
    top_k: int = 5,
    document_ids: list[UUID] | None = None,
    use_rag: bool = True,
    use_web: bool = False,
    rag_mode: str = "strict",
    web_max_results: int = 5,
    chat_model: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> ChatState:
    """Run classify + the appropriate retrieve branch + web search, returning
    a populated state ready for either `respond_node` or a streaming
    completion.

    Calls the same node functions the compiled graph uses (rather than
    re-implementing them) so the streaming path can't drift from `run_chat`.
    A parity test in test_agents_chat_workflow.py guards this.
    """
    state: ChatState = {
        "query": query,
        "user_id": user_id,
        "top_k": top_k,
        "document_ids": document_ids,
        "use_rag": use_rag,
        "use_web": use_web,
        "rag_mode": rag_mode,
        "web_max_results": web_max_results,
        "chat_model": chat_model,
        "history": history or [],
    }
    state.update(await classify_node(state))  # type: ignore[typeddict-item]

    branch = _route_after_classify(state)
    if branch == "skip_retrieval":
        state.update(await skip_retrieval_node(state))  # type: ignore[typeddict-item]
    elif branch == "fetch_summaries":
        state.update(await fetch_summaries_node(state))  # type: ignore[typeddict-item]
    elif branch == "retrieve_for_graph":
        state.update(await retrieve_for_graph_node(state))  # type: ignore[typeddict-item]
    else:
        state.update(await retrieve_for_chat_node(state))  # type: ignore[typeddict-item]

    state.update(await web_search_node(state))  # type: ignore[typeddict-item]
    return state


async def verify_node(state: ChatState) -> dict[str, Any]:
    # verify_answer maps every failure mode to a `skipped` verdict, so the
    # chat response never fails because of verification.
    async with time_node_async("verify"):
        result = await verify_answer(
            answer=state.get("answer", ""),
            chunks=state.get("chunks") or [],
            graph_facts=state.get("graph_facts") or [],
            web_results=state.get("web_results") or [],
        )
    return {"verification": result}


async def strict_gate_node(state: ChatState) -> dict[str, Any]:
    # Strict mode only meaningfully gates paths that produced verifiable
    # evidence — when verification skipped (summaries route, no context),
    # strict_refusal_for fails open.
    refusal = strict_refusal_for(
        state["verification"],
        rag_mode=state.get("rag_mode", "strict"),
        use_rag=state.get("use_rag", True),
    )
    if refusal is not None:
        # Replace the answer in-graph so run_chat output is self-consistent.
        return {"strict_refusal": refusal, "answer": refusal}
    return {"strict_refusal": None}


def build_chat_workflow():
    graph = StateGraph(ChatState)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve_for_chat", retrieve_for_chat_node)
    graph.add_node("fetch_summaries", fetch_summaries_node)
    graph.add_node("retrieve_for_graph", retrieve_for_graph_node)
    graph.add_node("skip_retrieval", skip_retrieval_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("respond", respond_node)
    graph.add_node("verify", verify_node)
    graph.add_node("strict_gate", strict_gate_node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {
            "retrieve_for_chat": "retrieve_for_chat",
            "fetch_summaries": "fetch_summaries",
            "retrieve_for_graph": "retrieve_for_graph",
            "skip_retrieval": "skip_retrieval",
        },
    )
    graph.add_edge("retrieve_for_chat", "web_search")
    graph.add_edge("fetch_summaries", "web_search")
    graph.add_edge("retrieve_for_graph", "web_search")
    graph.add_edge("skip_retrieval", "web_search")
    graph.add_edge("web_search", "respond")
    graph.add_edge("respond", "verify")
    graph.add_edge("verify", "strict_gate")
    graph.add_edge("strict_gate", END)
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
    use_rag: bool = True,
    use_web: bool = False,
    rag_mode: str = "strict",
    web_max_results: int = 5,
    chat_model: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> ChatState:
    initial: ChatState = {
        "query": query,
        "user_id": user_id,
        "top_k": top_k,
        "document_ids": document_ids,
        "use_rag": use_rag,
        "use_web": use_web,
        "rag_mode": rag_mode,
        "web_max_results": web_max_results,
        "chat_model": chat_model,
        "history": history or [],
    }
    final = await chat_workflow.ainvoke(initial)
    return final  # type: ignore[return-value]
