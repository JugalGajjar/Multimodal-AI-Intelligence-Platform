"""Tests for the SSE streaming chat endpoint and its helpers."""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.verification import VerificationResult
from app.rag import router as rag_router
from app.rag.graph_expansion import GraphFact
from app.rag.groq_chat import GroqChatError
from app.rag.retrieval import RetrievedChunk
from app.rag.schemas import ChatRequest


def _chunk(text: str = "hello") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        chunk_index=0,
        score=0.9,
        text=text,
    )


async def _drain(gen: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in gen]


def _parse_sse(chunks: list[bytes]) -> list[tuple[str, dict]]:
    """Parse raw SSE bytes into ordered (event, data) tuples."""
    events: list[tuple[str, dict]] = []
    for raw in chunks:
        text = raw.decode().strip()
        if not text:
            continue
        event_name = ""
        data_lines: list[str] = []
        for line in text.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_sse_formats_event_and_json_payload():
    raw = rag_router._sse("token", {"text": "hello"}).decode()
    assert raw.startswith("event: token\n")
    assert "data: " in raw
    assert raw.endswith("\n\n")
    body = raw.split("data: ", 1)[1].split("\n", 1)[0]
    assert json.loads(body) == {"text": "hello"}


class _StubUser:
    def __init__(self, rag_mode: str = "strict", web_max_results: int = 5):
        self.id = uuid4()
        self.rag_mode = rag_mode
        self.web_max_results = web_max_results


@pytest.mark.asyncio
async def test_stream_emits_meta_tokens_then_done():
    """Happy path: meta first, then one token per chunk, then done."""
    user = _StubUser()
    chunks = [_chunk("Qdrant is the vector DB.")]
    facts: list[GraphFact] = []

    async def fake_stream(**kwargs):
        for t in ["Qdrant ", "is ", "great."]:
            yield t

    state = {
        "query": "what is qdrant?",
        "user_id": user.id,
        "intent": "chat",
        "chunks": chunks,
        "graph_facts": facts,
        "used_context": True,
        "used_graph": False,
    }

    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
    ):
        payload = ChatRequest(query="what is qdrant?", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user)))  # type: ignore[arg-type]

    assert [e[0] for e in events] == ["meta", "token", "token", "token", "done"]

    meta = events[0][1]
    assert meta["intent"] == "chat"
    assert meta["used_context"] is True
    assert meta["used_graph"] is False
    assert len(meta["citations"]) == 1

    assert events[1][1] == {"text": "Qdrant "}
    assert events[2][1] == {"text": "is "}
    assert events[3][1] == {"text": "great."}

    done = events[4][1]
    assert done["verification"]["verdict"] == "verified"
    assert done["verification"]["groundedness_score"] == 1.0


@pytest.mark.asyncio
async def test_stream_emits_error_when_prepare_context_fails():
    user = _StubUser()
    with patch.object(
        rag_router,
        "prepare_context_state",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate"})),
    ):
        payload = ChatRequest(query="q", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user)))  # type: ignore[arg-type]

    assert len(events) == 1
    assert events[0][0] == "error"
    assert events[0][1]["status"] == 429


@pytest.mark.asyncio
async def test_stream_emits_error_when_token_stream_fails_mid_flight():
    """Meta should have been emitted; then an error event ends the stream."""
    user = _StubUser()
    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": [_chunk()],
        "graph_facts": [],
        "used_context": True,
        "used_graph": False,
    }

    async def fake_stream(**kwargs):
        yield "first "
        raise GroqChatError(429, {"detail": "rate"})

    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
    ):
        payload = ChatRequest(query="q", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user)))  # type: ignore[arg-type]

    assert [e[0] for e in events] == ["meta", "token", "error"]
    assert events[2][1]["status"] == 429


@pytest.mark.asyncio
async def test_stream_runs_verification_against_full_concatenated_answer():
    """The verify call must see the fully-joined answer text."""
    user = _StubUser()
    captured: dict = {}

    async def fake_stream(**kwargs):
        for t in ["A ", "B ", "C."]:
            yield t

    async def fake_verify(*, answer, chunks, graph_facts, web_results=None):
        captured["answer"] = answer
        return VerificationResult(verdict="verified", groundedness_score=1.0)

    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": [_chunk()],
        "graph_facts": [],
        "used_context": True,
        "used_graph": False,
    }
    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
        patch.object(rag_router, "verify_answer", new=fake_verify),
    ):
        payload = ChatRequest(query="q", top_k=3)
        await _drain(rag_router._stream_generator(payload, user))  # type: ignore[arg-type]

    assert captured["answer"] == "A B C."


@pytest.mark.asyncio
async def test_stream_meta_carries_intent_and_graph_flags():
    """Summarize and explain_graph branches must surface in `meta.intent`."""
    user = _StubUser()
    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "summarize",
        "chunks": [],
        "graph_facts": [],
        "used_context": True,
        "used_graph": False,
        "doc_summaries": [{"id": "d", "filename": "f.pdf", "tldr": "x"}],
    }

    async def fake_stream(**kwargs):
        yield "done"

    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
    ):
        payload = ChatRequest(query="recap", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user)))  # type: ignore[arg-type]

    meta = events[0][1]
    assert meta["intent"] == "summarize"


# ---------------------------------------------------------------------------
# Web citations + strict-mode signals
# ---------------------------------------------------------------------------


def _web_result(content: str = "fresh fact"):
    from app.rag.tavily import WebResult

    return WebResult(title="Page", url="https://w.com", content=content, score=0.9)


@pytest.mark.asyncio
async def test_stream_meta_carries_web_and_strict_fields():
    user = _StubUser(rag_mode="strict")
    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": [],
        "graph_facts": [],
        "web_results": [_web_result()],
        "used_context": False,
        "used_graph": False,
        "used_web": True,
    }

    async def fake_stream(**kwargs):
        yield "hi"

    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="verified", groundedness_score=1.0)
            ),
        ),
    ):
        payload = ChatRequest(query="q", use_web=True)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user)))  # type: ignore[arg-type]

    meta = events[0][1]
    assert meta["used_web"] is True
    assert meta["strict"] is True
    assert len(meta["web_citations"]) == 1
    assert meta["web_citations"][0]["url"] == "https://w.com"

    done = events[-1][1]
    assert done["strict_refusal"] is None


@pytest.mark.asyncio
async def test_stream_meta_strict_false_when_regular_or_rag_off():
    state = {
        "query": "q",
        "user_id": uuid4(),
        "intent": "chat",
        "chunks": [],
        "graph_facts": [],
        "used_context": False,
        "used_graph": False,
    }

    async def fake_stream(**kwargs):
        yield "hi"

    for user, payload in [
        (_StubUser(rag_mode="regular"), ChatRequest(query="q")),
        (_StubUser(rag_mode="strict"), ChatRequest(query="q", use_rag=False)),
    ]:
        with (
            patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
            patch.object(rag_router, "stream_chat_completion", new=fake_stream),
            patch.object(
                rag_router,
                "verify_answer",
                new=AsyncMock(
                    return_value=VerificationResult(verdict="skipped", groundedness_score=0.0)
                ),
            ),
        ):
            events = _parse_sse(
                await _drain(rag_router._stream_generator(payload, user))  # type: ignore[arg-type]
            )
        assert events[0][1]["strict"] is False


@pytest.mark.asyncio
async def test_stream_done_carries_refusal_when_strict_gate_fires():
    user = _StubUser(rag_mode="strict")
    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": [_chunk()],
        "graph_facts": [],
        "used_context": True,
        "used_graph": False,
    }

    async def fake_stream(**kwargs):
        yield "low quality answer"

    low = VerificationResult(verdict="unsupported", groundedness_score=0.2)
    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
        patch.object(rag_router, "verify_answer", new=AsyncMock(return_value=low)),
    ):
        payload = ChatRequest(query="q")
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user)))  # type: ignore[arg-type]

    done = events[-1][1]
    assert done["strict_refusal"] is not None
    assert "strict mode" in done["strict_refusal"]
    assert done["verification"]["groundedness_score"] == 0.2


@pytest.mark.asyncio
async def test_stream_verify_receives_web_results():
    user = _StubUser()
    captured: dict = {}

    async def fake_verify(*, answer, chunks, graph_facts, web_results=None):
        captured["web_results"] = web_results
        return VerificationResult(verdict="verified", groundedness_score=1.0)

    web = [_web_result("evidence")]
    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": [],
        "graph_facts": [],
        "web_results": web,
        "used_context": False,
        "used_graph": False,
        "used_web": True,
    }

    async def fake_stream(**kwargs):
        yield "x"

    with (
        patch.object(rag_router, "prepare_context_state", new=AsyncMock(return_value=state)),
        patch.object(rag_router, "stream_chat_completion", new=fake_stream),
        patch.object(rag_router, "verify_answer", new=fake_verify),
    ):
        payload = ChatRequest(query="q", use_web=True)
        await _drain(rag_router._stream_generator(payload, user))  # type: ignore[arg-type]

    assert captured["web_results"] == web
