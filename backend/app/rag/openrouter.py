"""Thin async client around OpenRouter's chat-completions endpoint."""

import httpx

from app.core.config import settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterError(Exception):
    """Wraps non-2xx responses from OpenRouter so callers can map to HTTP."""

    def __init__(self, status_code: int, body: object):
        super().__init__(f"OpenRouter returned {status_code}")
        self.status_code = status_code
        self.body = body


async def chat_completion(
    *,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> str:
    """Call OpenRouter and return the assistant text. Raises if no key set."""
    if not settings.openrouter_api_key:
        raise OpenRouterError(503, {"detail": "OPENROUTER_API_KEY not configured"})

    payload: dict = {
        "model": model or settings.openrouter_reasoning_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/mmap",
        "X-Title": "Multimodal AI Intelligence Platform",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )

    if response.status_code >= 400:
        try:
            body = response.json()
        except Exception:
            body = response.text
        raise OpenRouterError(response.status_code, body)

    data = response.json()
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(502, {"detail": "unexpected response shape", "body": data}) from exc
