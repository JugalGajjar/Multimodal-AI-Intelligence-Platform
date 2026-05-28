"""Async chat-completion wrapper around Groq's hosted LLMs.

Drop-in replacement for `app.rag.openrouter.chat_completion` — same signature,
same return type, same error semantics. Used by the `/api/v1/chat` endpoint.

OpenRouter is still used for vision (Groq doesn't host vision models yet).
"""

from typing import Any

from app.core.config import settings


class GroqChatError(Exception):
    """Wraps Groq SDK errors so callers can map to HTTP status codes."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Groq returned {status_code}")
        self.status_code = status_code
        self.body = body


async def chat_completion(
    *,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    timeout: float = 60.0,
) -> str:
    """Call Groq chat completions and return the assistant text.

    Raises GroqChatError(503) if no key is configured, or wraps the SDK's
    error as GroqChatError(<status>, body).
    """
    if not settings.groq_api_key:
        raise GroqChatError(503, {"detail": "GROQ_API_KEY not configured"})

    try:
        from groq import AsyncGroq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GroqChatError(500, {"detail": f"groq SDK not installed: {exc}"}) from exc

    client = AsyncGroq(api_key=settings.groq_api_key, timeout=timeout)
    create_kwargs: dict = {
        "model": model or settings.groq_reasoning_model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens or 4096,
    }
    if response_format is not None:
        create_kwargs["response_format"] = response_format

    try:
        completion = await client.chat.completions.create(**create_kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001  — Groq SDK raises various subclasses
        status_attr = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        status_code = int(status_attr) if status_attr is not None else 502
        try:
            body = (
                getattr(exc, "body", None) or getattr(exc, "response", None) or {"error": str(exc)}
            )
        except Exception:  # noqa: BLE001
            body = {"error": str(exc)}
        raise GroqChatError(status_code, body) from exc

    try:
        content = completion.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise GroqChatError(502, {"detail": "unexpected Groq response shape"}) from exc

    return str(content or "")
