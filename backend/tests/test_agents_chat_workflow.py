"""Unit tests for the LangGraph chat workflow (Phase 5.1).

These cover behaviour, not LangGraph internals — we verify that the workflow
threads inputs through the right nodes, returns a state shape the FastAPI
layer can consume, and lets upstream errors propagate.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents import chat_workflow as wf
from app.rag.graph_expansion import GraphFact, GraphRelation
from app.rag.groq_chat import GroqChatError
from app.rag.retrieval import RetrievedChunk


def _chunk(text: str = "hello") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        chunk_index=0,
        score=0.9,
        text=text,
    )


def _fact() -> GraphFact:
    return GraphFact(
        name="Qdrant",
        type="Technology",
        description="vector DB",
        relations=[
            GraphRelation(
                relation="uses",
                other="Cosine Distance",
                distance=1,
                relation_chain=["uses"],
            )
        ],
    )


@pytest.mark.asyncio
async def test_run_chat_returns_answer_chunks_and_facts():
    """Happy path: retrieve fills chunks+facts, respond fills answer+model."""
    chunks = [_chunk("Qdrant is a vector DB")]
    facts = [_fact()]

    with (
        patch.object(wf, "retrieve", return_value=chunks),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=facts)),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="42")),
    ):
        state = await wf.run_chat(query="what is qdrant?", user_id=uuid4())

    assert state["answer"] == "42"
    assert state["chunks"] == chunks
    assert state["graph_facts"] == facts
    assert state["used_context"] is True
    assert state["used_graph"] is True


@pytest.mark.asyncio
async def test_run_chat_marks_no_context_when_retrieval_returns_empty():
    with (
        patch.object(wf, "retrieve", return_value=[]),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="I don't know.")),
    ):
        state = await wf.run_chat(query="anything", user_id=uuid4())

    assert state["used_context"] is False
    assert state["used_graph"] is False
    assert state["chunks"] == []
    assert state["graph_facts"] == []


@pytest.mark.asyncio
async def test_run_chat_uses_no_context_fallback_system_prompt(monkeypatch):
    """When retrieval and graph both return empty, respond_node must switch
    to the fallback system prompt (not pretend to have context)."""
    captured: dict = {}

    async def fake_chat(*, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return "ok"

    monkeypatch.setattr(wf, "chat_completion", fake_chat)
    monkeypatch.setattr(wf, "retrieve", lambda **kwargs: [])
    monkeypatch.setattr(wf, "_safe_expand", AsyncMock(return_value=[]))

    await wf.run_chat(query="hi", user_id=uuid4())

    from app.rag.prompts import NO_CONTEXT_FALLBACK_SYSTEM, SYSTEM_PROMPT

    assert captured["system"] == NO_CONTEXT_FALLBACK_SYSTEM
    assert captured["system"] != SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_run_chat_propagates_groq_errors():
    """Upstream LLM errors should bubble so FastAPI can map status codes."""
    with (
        patch.object(wf, "retrieve", return_value=[_chunk()]),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(
            wf,
            "chat_completion",
            new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate limit"})),
        ),
        pytest.raises(GroqChatError) as exc,
    ):
        await wf.run_chat(query="hi", user_id=uuid4())

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_safe_expand_swallows_graph_errors():
    """_safe_expand is the seam that makes Neo4j outage non-fatal for chat."""
    with patch.object(
        wf,
        "expand_with_graph",
        new=AsyncMock(side_effect=RuntimeError("neo4j down")),
    ):
        result = await wf._safe_expand("q", [], uuid4())

    assert result == []


@pytest.mark.asyncio
async def test_workflow_passes_top_k_and_document_ids_to_retrieve():
    """Inputs from ChatRequest must reach the retrieve call unchanged."""
    captured: dict = {}

    def fake_retrieve(*, query, user_id, top_k, document_ids):
        captured.update(
            {"query": query, "user_id": user_id, "top_k": top_k, "document_ids": document_ids}
        )
        return []

    doc_id = uuid4()
    with (
        patch.object(wf, "retrieve", side_effect=fake_retrieve),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="ok")),
    ):
        await wf.run_chat(
            query="explicit",
            user_id=uuid4(),
            top_k=7,
            document_ids=[doc_id],
        )

    assert captured["query"] == "explicit"
    assert captured["top_k"] == 7
    assert captured["document_ids"] == [doc_id]


@pytest.mark.asyncio
async def test_compiled_workflow_executes_nodes_in_order():
    """Smoke check: building + invoking the StateGraph end-to-end works
    without LangGraph configuration mistakes (missing edges, etc.)."""
    chunks = [_chunk()]
    with (
        patch.object(wf, "retrieve", return_value=chunks),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="done")),
    ):
        compiled = wf.build_chat_workflow()
        final = await compiled.ainvoke({"query": "go", "user_id": uuid4(), "top_k": 3})

    assert final["answer"] == "done"
    assert final["chunks"] == chunks
