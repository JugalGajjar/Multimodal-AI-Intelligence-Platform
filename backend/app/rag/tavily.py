"""Thin async client around Tavily's search endpoint."""

from dataclasses import dataclass

import httpx

from app.core.config import settings

TAVILY_BASE_URL = "https://api.tavily.com"


class TavilyError(Exception):
    def __init__(self, status_code: int, body: object):
        super().__init__(f"Tavily returned {status_code}")
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    content: str
    score: float


async def search_web(
    *,
    query: str,
    max_results: int = 5,
    timeout: float | None = None,
) -> list[WebResult]:
    if not settings.tavily_api_key:
        raise TavilyError(503, {"detail": "TAVILY_API_KEY not configured"})

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": max(1, min(10, max_results)),
        "include_answer": False,
    }

    async with httpx.AsyncClient(timeout=timeout or settings.tavily_timeout_sec) as client:
        response = await client.post(f"{TAVILY_BASE_URL}/search", json=payload)

    if response.status_code >= 400:
        try:
            body = response.json()
        except Exception:
            body = response.text
        raise TavilyError(response.status_code, body)

    data = response.json()
    items = data.get("results") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise TavilyError(502, {"detail": "unexpected response shape", "body": data})

    out: list[WebResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        out.append(
            WebResult(
                title=str(item.get("title") or "").strip(),
                url=url,
                content=str(item.get("content") or "").strip(),
                score=float(item.get("score") or 0.0),
            )
        )
    return out
