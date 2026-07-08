"""Unit tests for the Groq chat-completion wrapper. SDK is fully mocked."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.rag import groq_chat


def _install_fake_groq(monkeypatch, async_client):
    """Inject a fake `groq` module with AsyncGroq pointing at *async_client*."""
    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(return_value=async_client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)


def _fake_completion(text: str):
    msg = MagicMock(content=text)
    choice = MagicMock(message=msg)
    return MagicMock(choices=[choice])


async def test_raises_503_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")

    with pytest.raises(groq_chat.GroqChatError) as exc:
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "hi"}])

    assert exc.value.status_code == 503


async def test_returns_assistant_text_on_success(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")
    monkeypatch.setattr(settings, "groq_reasoning_model", "vendor/test-model")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_completion("the answer"))
    _install_fake_groq(monkeypatch, client)

    out = await groq_chat.chat_completion(messages=[{"role": "user", "content": "ping"}])

    assert out == "the answer"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "vendor/test-model"
    assert kwargs["messages"][0]["content"] == "ping"
    assert kwargs["temperature"] == pytest.approx(0.2)


async def test_custom_model_overrides_default(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")
    monkeypatch.setattr(settings, "groq_reasoning_model", "default-model")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
    _install_fake_groq(monkeypatch, client)

    await groq_chat.chat_completion(
        messages=[{"role": "user", "content": "x"}],
        model="custom/model",
    )

    assert client.chat.completions.create.call_args.kwargs["model"] == "custom/model"


async def test_sdk_error_wrapped_in_groq_chat_error(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    err = RuntimeError("upstream 429")
    err.status_code = 429
    err.body = {"detail": "rate limited"}

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=err)
    _install_fake_groq(monkeypatch, client)

    with pytest.raises(groq_chat.GroqChatError) as exc:
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert exc.value.status_code == 429
    assert "rate limited" in str(exc.value.body)


async def test_unexpected_response_shape_raises_502(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    # Completion with no `choices`
    bad = MagicMock(choices=[])
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=bad)
    _install_fake_groq(monkeypatch, client)

    with pytest.raises(groq_chat.GroqChatError) as exc:
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert exc.value.status_code == 502


async def test_passes_max_completion_tokens(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
    _install_fake_groq(monkeypatch, client)

    await groq_chat.chat_completion(
        messages=[{"role": "user", "content": "x"}],
        max_tokens=2000,
    )

    assert client.chat.completions.create.call_args.kwargs["max_completion_tokens"] == 2000


async def test_forwards_reasoning_effort_when_set(monkeypatch):
    """gpt-oss models accept `reasoning_effort` to bound CoT tokens. Callers
    that pass it must have it forwarded to the SDK verbatim. Not passing means
    the extraction-side #41 fix silently regresses."""
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
    _install_fake_groq(monkeypatch, client)

    await groq_chat.chat_completion(
        messages=[{"role": "user", "content": "x"}],
        reasoning_effort="low",
    )

    assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "low"


async def test_omits_reasoning_effort_when_not_set(monkeypatch):
    """Backward-compat: callers that don't pass reasoning_effort should not
    have the key sent — some models reject it."""
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
    _install_fake_groq(monkeypatch, client)

    await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert "reasoning_effort" not in client.chat.completions.create.call_args.kwargs


# ---------------------------------------------------------------------------
# Key pool rotation
# ---------------------------------------------------------------------------


def _reset_key_cycle():
    # Ensure each test starts from a fresh rotation state — module-level.
    groq_chat._KEY_CYCLE = None
    groq_chat._CURRENT_POOL = ()


async def test_key_pool_round_robin_distributes_calls(monkeypatch):
    """With N keys configured, N consecutive calls should each use a
    different key (round-robin). Verifies the rotation logic sees every
    key in the pool before wrapping."""
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "gsk_a, gsk_b, gsk_c")

    seen_keys: list[str] = []

    def async_groq_ctor(*, api_key, **_kwargs):
        seen_keys.append(api_key)
        c = MagicMock()
        c.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    for _ in range(3):
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert seen_keys == ["gsk_a", "gsk_b", "gsk_c"]


async def test_key_pool_wraps_on_more_calls_than_keys(monkeypatch):
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "gsk_a,gsk_b")

    seen_keys: list[str] = []

    def async_groq_ctor(*, api_key, **_kwargs):
        seen_keys.append(api_key)
        c = MagicMock()
        c.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    for _ in range(5):
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    # 5 calls across 2 keys → each key at least twice, none skipped.
    assert seen_keys.count("gsk_a") >= 2
    assert seen_keys.count("gsk_b") >= 2
    assert set(seen_keys) == {"gsk_a", "gsk_b"}


async def test_single_key_fallback_when_pool_env_is_empty(monkeypatch):
    """Backward-compat: no groq_api_keys env → use groq_api_key as a
    one-element pool. Existing single-key deploys stay identical."""
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_keys", "")
    monkeypatch.setattr(settings, "groq_api_key", "gsk_only")

    seen_keys: list[str] = []

    def async_groq_ctor(*, api_key, **_kwargs):
        seen_keys.append(api_key)
        c = MagicMock()
        c.chat.completions.create = AsyncMock(return_value=_fake_completion("ok"))
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    for _ in range(3):
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert seen_keys == ["gsk_only", "gsk_only", "gsk_only"]


async def test_fallthrough_on_429_tries_next_key(monkeypatch):
    """Key A returns 429; the same call should immediately retry with key B
    and succeed, without any explicit caller-side retry logic."""
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "gsk_a,gsk_b")

    err = RuntimeError("rate limit")
    err.status_code = 429
    err.body = {"detail": "rate"}

    ok_completion = _fake_completion("recovered")
    seen_keys: list[str] = []

    def async_groq_ctor(*, api_key, **_kwargs):
        seen_keys.append(api_key)
        c = MagicMock()
        if api_key == "gsk_a":
            c.chat.completions.create = AsyncMock(side_effect=err)
        else:
            c.chat.completions.create = AsyncMock(return_value=ok_completion)
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    out = await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert out == "recovered"
    assert seen_keys == ["gsk_a", "gsk_b"]


async def test_fallthrough_on_413_tries_next_key(monkeypatch):
    """413 (Payload Too Large — free-tier per-request TPM ceiling) is the
    same class as 429 for pool purposes: try the next key first."""
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "gsk_a,gsk_b")

    err = RuntimeError("payload too large")
    err.status_code = 413
    err.body = {"detail": "tpm"}

    ok_completion = _fake_completion("recovered")

    def async_groq_ctor(*, api_key, **_kwargs):
        c = MagicMock()
        if api_key == "gsk_a":
            c.chat.completions.create = AsyncMock(side_effect=err)
        else:
            c.chat.completions.create = AsyncMock(return_value=ok_completion)
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    out = await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])
    assert out == "recovered"


async def test_non_throttle_errors_do_not_fallthrough(monkeypatch):
    """400 (json_validate_failed), 401 (auth), 5xx (server) — swapping keys
    won't help. These must bubble up on the first key, not burn the pool."""
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "gsk_a,gsk_b,gsk_c")

    err = RuntimeError("bad json")
    err.status_code = 400
    err.body = {"error": {"code": "json_validate_failed"}}

    seen_keys: list[str] = []

    def async_groq_ctor(*, api_key, **_kwargs):
        seen_keys.append(api_key)
        c = MagicMock()
        c.chat.completions.create = AsyncMock(side_effect=err)
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    with pytest.raises(groq_chat.GroqChatError) as exc:
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert exc.value.status_code == 400
    # Only one key attempted — no wasted calls to other keys.
    assert seen_keys == ["gsk_a"]


async def test_all_keys_throttled_bubbles_up_final_error(monkeypatch):
    """Every key in the pool 429s → final 429 raised. Don't loop forever."""
    _reset_key_cycle()
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "groq_api_keys", "gsk_a,gsk_b")

    err = RuntimeError("rate")
    err.status_code = 429
    err.body = {"detail": "rate"}

    seen_keys: list[str] = []

    def async_groq_ctor(*, api_key, **_kwargs):
        seen_keys.append(api_key)
        c = MagicMock()
        c.chat.completions.create = AsyncMock(side_effect=err)
        return c

    fake_module = types.ModuleType("groq")
    fake_module.AsyncGroq = MagicMock(side_effect=async_groq_ctor)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    with pytest.raises(groq_chat.GroqChatError) as exc:
        await groq_chat.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert exc.value.status_code == 429
    # Every key tried exactly once — no more, no less.
    assert set(seen_keys) == {"gsk_a", "gsk_b"}
    assert len(seen_keys) == 2
