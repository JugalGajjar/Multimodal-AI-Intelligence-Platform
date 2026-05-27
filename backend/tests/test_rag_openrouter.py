"""Unit tests for the OpenRouter HTTP wrapper. All network is mocked."""

import httpx
import pytest

from app.core.config import settings
from app.rag import openrouter


def _httpx_mock_response(json_body: dict | None = None, status: int = 200):
    return httpx.Response(
        status,
        json=json_body if json_body is not None else {},
        request=httpx.Request("POST", openrouter.OPENROUTER_BASE_URL),
    )


async def test_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    with pytest.raises(openrouter.OpenRouterError) as exc:
        await openrouter.chat_completion(messages=[{"role": "user", "content": "hi"}])

    assert exc.value.status_code == 503


async def test_returns_assistant_text_on_success(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    captured: dict = {}

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return _httpx_mock_response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "the answer"},
                        "index": 0,
                    }
                ]
            }
        )

    transport = httpx.MockTransport(transport_handler)
    orig_client = httpx.AsyncClient

    class _Patched(orig_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Patched)

    out = await openrouter.chat_completion(
        messages=[{"role": "user", "content": "ping"}],
        model="m/x",
    )

    assert out == "the answer"
    assert "/chat/completions" in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer fake-key"
    import json

    payload = json.loads(captured["body"])
    assert payload["model"] == "m/x"
    assert payload["messages"][0]["content"] == "ping"


async def test_raises_on_upstream_4xx(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    def handler(_req):
        return _httpx_mock_response({"error": "rate limited"}, status=429)

    transport = httpx.MockTransport(handler)

    class _Patched(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _Patched)

    with pytest.raises(openrouter.OpenRouterError) as exc:
        await openrouter.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert exc.value.status_code == 429


async def test_raises_on_malformed_response(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    def handler(_req):
        return _httpx_mock_response({"unexpected": "shape"})

    transport = httpx.MockTransport(handler)

    class _Patched(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _Patched)

    with pytest.raises(openrouter.OpenRouterError) as exc:
        await openrouter.chat_completion(messages=[{"role": "user", "content": "x"}])

    assert exc.value.status_code == 502
