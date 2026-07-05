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
    def __init__(
        self,
        rag_mode: str = "strict",
        web_max_results: int = 5,
        chat_model: str | None = None,
    ):
        self.id = uuid4()
        self.rag_mode = rag_mode
        self.web_max_results = web_max_results
        self.chat_model = chat_model


def _ctx(
    *,
    created_now: bool = True,
    is_first_turn: bool = True,
    next_seq: int = 0,
    history: list[dict] | None = None,
) -> "rag_router._ChatCtx":
    return rag_router._ChatCtx(
        chat_id=uuid4(),
        created_now=created_now,
        is_first_turn=is_first_turn,
        next_seq=next_seq,
        history=history or [],
    )


@pytest.fixture(autouse=True)
def _mock_chat_persistence():
    """Persistence is exercised by dedicated tests below; keep the rest of
    the suite focused on SSE behavior."""
    with (
        patch.object(rag_router, "persist_turn", new=AsyncMock()) as persist,
        patch.object(rag_router, "refresh_chat_summary", new=AsyncMock()) as refresh,
        patch.object(rag_router, "delete_chat_row", new=AsyncMock()) as cleanup,
    ):
        yield {"persist": persist, "refresh": refresh, "cleanup": cleanup}


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
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

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
async def test_stream_uses_user_chat_model_in_meta_and_persist(_mock_chat_persistence):
    """When the user has picked a non-default model in Settings, that id
    should appear in the meta event, be passed to stream_chat_completion,
    and land in the persisted response_meta."""
    user = _StubUser(chat_model="qwen/qwen3-32b")
    chunks = [_chunk("Qdrant.")]
    seen_stream_kwargs: dict = {}

    async def fake_stream(**kwargs):
        seen_stream_kwargs.update(kwargs)
        for t in ["hi"]:
            yield t

    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": chunks,
        "graph_facts": [],
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
        payload = ChatRequest(query="q", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

    meta = events[0][1]
    assert meta["model"] == "qwen/qwen3-32b"
    # stream_chat_completion was called with the user's chosen model, not the
    # global default.
    assert seen_stream_kwargs.get("model") == "qwen/qwen3-32b"
    # persist_turn's response_meta records what actually answered the turn.
    persist_call = _mock_chat_persistence["persist"].await_args
    assert persist_call.kwargs["response_meta"]["model"] == "qwen/qwen3-32b"


@pytest.mark.asyncio
async def test_stream_falls_back_to_default_model_when_user_has_no_override(
    _mock_chat_persistence,
):
    """A user with chat_model=None (fresh account) should see the server
    default in meta.model — no leaking of a wrong or empty id."""
    from app.core.config import settings as _settings

    user = _StubUser(chat_model=None)
    chunks = [_chunk("x.")]

    async def fake_stream(**kwargs):
        yield "hi"

    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": chunks,
        "graph_facts": [],
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
        payload = ChatRequest(query="q", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

    assert events[0][1]["model"] == _settings.groq_reasoning_model


@pytest.mark.asyncio
async def test_stream_emits_error_when_prepare_context_fails():
    user = _StubUser()
    with patch.object(
        rag_router,
        "prepare_context_state",
        new=AsyncMock(side_effect=GroqChatError(429, {"detail": "rate"})),
    ):
        payload = ChatRequest(query="q", top_k=3)
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

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
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

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
        await _drain(rag_router._stream_generator(payload, user, _ctx()))  # type: ignore[arg-type]

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
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

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
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

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
                await _drain(rag_router._stream_generator(payload, user, _ctx()))  # type: ignore[arg-type]
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
        events = _parse_sse(await _drain(rag_router._stream_generator(payload, user, _ctx())))  # type: ignore[arg-type]

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
        await _drain(rag_router._stream_generator(payload, user, _ctx()))  # type: ignore[arg-type]

    assert captured["web_results"] == web


# ---------------------------------------------------------------------------
# Chat persistence
# ---------------------------------------------------------------------------


def _basic_state(user, **over):
    state = {
        "query": "q",
        "user_id": user.id,
        "intent": "chat",
        "chunks": [],
        "graph_facts": [],
        "used_context": False,
        "used_graph": False,
    }
    state.update(over)
    return state


async def _one_token(**kwargs):
    yield "answer text"


@pytest.mark.asyncio
async def test_stream_meta_carries_chat_id(_mock_chat_persistence):
    user = _StubUser()
    ctx = _ctx()
    with (
        patch.object(
            rag_router,
            "prepare_context_state",
            new=AsyncMock(return_value=_basic_state(user)),
        ),
        patch.object(rag_router, "stream_chat_completion", new=_one_token),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="skipped", groundedness_score=0.0)
            ),
        ),
    ):
        payload = ChatRequest(query="q")
        events = _parse_sse(
            await _drain(rag_router._stream_generator(payload, user, ctx))  # type: ignore[arg-type]
        )

    assert events[0][1]["chat_id"] == str(ctx.chat_id)


@pytest.mark.asyncio
async def test_history_reaches_prepare_context_state(_mock_chat_persistence):
    user = _StubUser()
    history = [
        {"role": "user", "content": "earlier q"},
        {"role": "assistant", "content": "earlier a"},
    ]
    prepare = AsyncMock(return_value=_basic_state(user))
    with (
        patch.object(rag_router, "prepare_context_state", new=prepare),
        patch.object(rag_router, "stream_chat_completion", new=_one_token),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="skipped", groundedness_score=0.0)
            ),
        ),
    ):
        payload = ChatRequest(query="q")
        await _drain(
            rag_router._stream_generator(payload, user, _ctx(history=history))  # type: ignore[arg-type]
        )

    assert prepare.call_args.kwargs["history"] == history


@pytest.mark.asyncio
async def test_persist_turn_receives_refusal_when_gated(_mock_chat_persistence):
    user = _StubUser(rag_mode="strict")
    low = VerificationResult(verdict="unsupported", groundedness_score=0.1)
    ctx = _ctx(next_seq=4, is_first_turn=False)
    with (
        patch.object(
            rag_router,
            "prepare_context_state",
            new=AsyncMock(return_value=_basic_state(user, chunks=[_chunk()], used_context=True)),
        ),
        patch.object(rag_router, "stream_chat_completion", new=_one_token),
        patch.object(rag_router, "verify_answer", new=AsyncMock(return_value=low)),
    ):
        payload = ChatRequest(query="q")
        await _drain(rag_router._stream_generator(payload, user, ctx))  # type: ignore[arg-type]

    persist = _mock_chat_persistence["persist"]
    persist.assert_awaited_once()
    kwargs = persist.call_args.kwargs
    assert "strict mode" in kwargs["answer"]
    assert kwargs["answer"] != "answer text"
    assert kwargs["response_meta"]["strict_refusal"] is True
    assert kwargs["next_seq"] == 4
    # Summary refresh sees the refusal too, and no title for a later turn.
    refresh = _mock_chat_persistence["refresh"]
    assert refresh.call_args.kwargs["generate_title"] is False
    assert refresh.call_args.kwargs["turns"][-1]["content"] == kwargs["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("created_now", [True, False])
async def test_mid_stream_error_persists_nothing(created_now, _mock_chat_persistence):
    user = _StubUser()

    async def failing_stream(**kwargs):
        yield "partial "
        raise GroqChatError(429, {"detail": "rate"})

    ctx = _ctx(created_now=created_now)
    with (
        patch.object(
            rag_router,
            "prepare_context_state",
            new=AsyncMock(return_value=_basic_state(user)),
        ),
        patch.object(rag_router, "stream_chat_completion", new=failing_stream),
    ):
        payload = ChatRequest(query="q")
        events = _parse_sse(
            await _drain(rag_router._stream_generator(payload, user, ctx))  # type: ignore[arg-type]
        )

    assert events[-1][0] == "error"
    _mock_chat_persistence["persist"].assert_not_awaited()
    cleanup = _mock_chat_persistence["cleanup"]
    if created_now:
        cleanup.assert_awaited_once_with(ctx.chat_id)
    else:
        cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_title_generated_only_on_first_turn(_mock_chat_persistence):
    user = _StubUser()
    with (
        patch.object(
            rag_router,
            "prepare_context_state",
            new=AsyncMock(return_value=_basic_state(user)),
        ),
        patch.object(rag_router, "stream_chat_completion", new=_one_token),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="skipped", groundedness_score=0.0)
            ),
        ),
    ):
        payload = ChatRequest(query="q")
        await _drain(
            rag_router._stream_generator(payload, user, _ctx(is_first_turn=True))  # type: ignore[arg-type]
        )

    assert _mock_chat_persistence["refresh"].call_args.kwargs["generate_title"] is True


@pytest.mark.asyncio
async def test_persistence_failure_emits_no_extra_sse_bytes(_mock_chat_persistence):
    user = _StubUser()
    _mock_chat_persistence["persist"].side_effect = RuntimeError("db down")
    with (
        patch.object(
            rag_router,
            "prepare_context_state",
            new=AsyncMock(return_value=_basic_state(user)),
        ),
        patch.object(rag_router, "stream_chat_completion", new=_one_token),
        patch.object(
            rag_router,
            "verify_answer",
            new=AsyncMock(
                return_value=VerificationResult(verdict="skipped", groundedness_score=0.0)
            ),
        ),
    ):
        payload = ChatRequest(query="q")
        events = _parse_sse(
            await _drain(rag_router._stream_generator(payload, user, _ctx()))  # type: ignore[arg-type]
        )

    # Stream is intact and ends at `done` — the persistence failure is silent.
    assert [e[0] for e in events] == ["meta", "token", "done"]
