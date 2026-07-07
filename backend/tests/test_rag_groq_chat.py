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
