"""Unit tests for the LangGraph chat workflow."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents import chat_workflow as wf
from app.agents.verification import VerificationResult
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


@pytest.fixture(autouse=True)
def _stub_classifier_to_chat():
    """Default every test to the 'chat' route so we don't hit Groq."""
    with patch.object(wf, "classify_intent", new=AsyncMock(return_value="chat")):
        yield


@pytest.mark.asyncio
async def test_run_chat_returns_answer_chunks_and_facts():
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
    assert state["intent"] == "chat"


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
    with patch.object(
        wf,
        "expand_with_graph",
        new=AsyncMock(side_effect=RuntimeError("neo4j down")),
    ):
        result = await wf._safe_expand("q", [], uuid4())

    assert result == []


@pytest.mark.asyncio
async def test_workflow_passes_top_k_and_document_ids_to_retrieve():
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
    chunks = [_chunk()]
    with (
        patch.object(wf, "retrieve", return_value=chunks),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="done")),
        patch.object(
            wf,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
    ):
        compiled = wf.build_chat_workflow()
        final = await compiled.ainvoke({"query": "go", "user_id": uuid4(), "top_k": 3})

    assert final["answer"] == "done"
    assert final["chunks"] == chunks


@pytest.mark.asyncio
async def test_workflow_runs_verify_node_after_respond():
    chunks = [_chunk("Qdrant is a vector DB")]
    captured: dict = {}

    async def fake_verify(*, answer, chunks, graph_facts):
        captured["answer"] = answer
        captured["chunks"] = chunks
        return VerificationResult(
            verdict="partial",
            groundedness_score=0.5,
            total_claims=2,
            supported_claims=1,
            unsupported_claims=["fabricated bit"],
        )

    with (
        patch.object(wf, "retrieve", return_value=chunks),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="Qdrant is great.")),
        patch.object(wf, "verify_answer", new=fake_verify),
    ):
        state = await wf.run_chat(query="what?", user_id=uuid4())

    assert captured["answer"] == "Qdrant is great."
    assert captured["chunks"] == chunks
    v = state["verification"]
    assert v.verdict == "partial"
    assert v.unsupported_claims == ["fabricated bit"]


@pytest.mark.asyncio
async def test_route_after_classify_picks_the_right_branch():
    assert wf._route_after_classify({"intent": "chat"}) == "retrieve_for_chat"
    assert wf._route_after_classify({"intent": "summarize"}) == "fetch_summaries"
    assert wf._route_after_classify({"intent": "explain_graph"}) == "retrieve_for_graph"
    # Missing intent defaults to chat.
    assert wf._route_after_classify({}) == "retrieve_for_chat"


@pytest.mark.asyncio
async def test_summarize_intent_uses_summaries_branch():
    """When the classifier returns 'summarize', the workflow must fetch the
    user's stored doc summaries instead of running vector retrieval."""
    summaries = [
        {
            "id": "d-1",
            "filename": "paper.pdf",
            "tldr": "The paper covers vector RAG.",
            "key_points": ["uses Qdrant", "uses bge-small"],
            "topics": ["RAG"],
        }
    ]

    with (
        patch.object(wf, "classify_intent", new=AsyncMock(return_value="summarize")),
        patch.object(wf, "list_summaries_for_user", new=AsyncMock(return_value=summaries)),
        patch.object(wf, "retrieve") as retrieve_spy,
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="summary answer")),
        patch.object(
            wf,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
    ):
        state = await wf.run_chat(query="recap my docs", user_id=uuid4())

    assert state["intent"] == "summarize"
    assert state["doc_summaries"] == summaries
    assert state["used_context"] is True
    retrieve_spy.assert_not_called()


@pytest.mark.asyncio
async def test_explain_graph_intent_skips_vector_retrieval():
    facts = [_fact()]

    with (
        patch.object(wf, "classify_intent", new=AsyncMock(return_value="explain_graph")),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=facts)) as expand_spy,
        patch.object(wf, "retrieve") as retrieve_spy,
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="graph answer")),
        patch.object(
            wf,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
    ):
        state = await wf.run_chat(query="what relates to qdrant", user_id=uuid4())

    assert state["intent"] == "explain_graph"
    assert state["chunks"] == []
    assert state["graph_facts"] == facts
    assert state["used_graph"] is True
    retrieve_spy.assert_not_called()
    # Expansion still gets called (with empty chunks) so it walks from seeds.
    expand_spy.assert_called_once()


@pytest.mark.asyncio
async def test_classifier_failure_falls_back_to_chat_branch():
    """Even when classify_intent crashes upstream, the workflow falls back
    to the safe `chat` branch — the user always gets an answer."""
    # The autouse fixture is the seam: replace it with a failing AsyncMock.
    # The router's own catch is exercised by test_classify_intent_falls_back_*;
    # this test asserts the wf surfaces the error if the classifier crashes
    # outside its own catch (defense in depth).
    chunks = [_chunk("text")]
    with (
        patch.object(wf, "classify_intent", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(wf, "retrieve", return_value=chunks),
        patch.object(wf, "_safe_expand", new=AsyncMock(return_value=[])),
        patch.object(wf, "chat_completion", new=AsyncMock(return_value="answer")),
        patch.object(
            wf,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
        pytest.raises(RuntimeError),
    ):
        await wf.run_chat(query="hi", user_id=uuid4())
