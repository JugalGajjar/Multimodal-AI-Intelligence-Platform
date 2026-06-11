"""Unit tests for the Tavily web-search client. HTTP is mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.rag import tavily
from app.rag.tavily import TavilyError, WebResult


@pytest.fixture(autouse=True)
def _tavily_key(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "fake-key")


def _response(status_code: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _client_returning(resp: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


async def test_raises_503_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "")

    with pytest.raises(TavilyError) as exc:
        await tavily.search_web(query="anything")

    assert exc.value.status_code == 503


async def test_happy_path_parses_results():
    data = {
        "results": [
            {"title": "T1", "url": "https://a.com", "content": "alpha", "score": 0.9},
            {"title": "T2", "url": "https://b.com", "content": "beta", "score": 0.5},
        ]
    }
    client = _client_returning(_response(200, data))

    with patch.object(tavily.httpx, "AsyncClient", return_value=client):
        out = await tavily.search_web(query="q", max_results=2)

    assert out == [
        WebResult(title="T1", url="https://a.com", content="alpha", score=0.9),
        WebResult(title="T2", url="https://b.com", content="beta", score=0.5),
    ]
    payload = client.post.call_args.kwargs["json"]
    assert payload["query"] == "q"
    assert payload["max_results"] == 2
    assert payload["include_answer"] is False


async def test_http_error_raises_tavily_error():
    client = _client_returning(_response(429, {"detail": "rate limited"}))

    with (
        patch.object(tavily.httpx, "AsyncClient", return_value=client),
        pytest.raises(TavilyError) as exc,
    ):
        await tavily.search_web(query="q")

    assert exc.value.status_code == 429


async def test_malformed_entries_are_skipped():
    data = {
        "results": [
            {"title": "no url", "content": "x"},
            "not-a-dict",
            {"title": "ok", "url": "https://ok.com", "content": "y", "score": 0.1},
        ]
    }
    client = _client_returning(_response(200, data))

    with patch.object(tavily.httpx, "AsyncClient", return_value=client):
        out = await tavily.search_web(query="q")

    assert len(out) == 1
    assert out[0].url == "https://ok.com"


async def test_unexpected_shape_raises_502():
    client = _client_returning(_response(200, {"nope": True}))

    with (
        patch.object(tavily.httpx, "AsyncClient", return_value=client),
        pytest.raises(TavilyError) as exc,
    ):
        await tavily.search_web(query="q")

    assert exc.value.status_code == 502


async def test_max_results_clamped_to_1_10():
    client = _client_returning(_response(200, {"results": []}))

    with patch.object(tavily.httpx, "AsyncClient", return_value=client):
        await tavily.search_web(query="q", max_results=99)
        assert client.post.call_args.kwargs["json"]["max_results"] == 10
        await tavily.search_web(query="q", max_results=0)
        assert client.post.call_args.kwargs["json"]["max_results"] == 1
