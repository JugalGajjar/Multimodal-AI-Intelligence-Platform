"""Async chat-completion wrapper around Groq."""

import itertools
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import settings
from app.core.metrics import time_llm


class GroqChatError(Exception):
    # Wraps Groq SDK errors so callers can map to HTTP status codes.
    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Groq returned {status_code}")
        self.status_code = status_code
        self.body = body


_KEY_CYCLE: "itertools.cycle[str] | None" = None
_CURRENT_POOL: tuple[str, ...] = ()

# Errors that indicate the key itself is throttled — worth trying another
# key in the pool before bubbling up. Non-throttle errors (auth, schema,
# server 5xx) do NOT trigger a fallthrough since another key won't help.
_FALLTHROUGH_STATUSES = frozenset({429, 413})


def _pick_key(exclude: set[str] | None = None) -> str:
    """Return the next key in rotation, skipping any in *exclude*.

    Re-materialises the cycle iterator whenever the configured pool changes
    (settings live-reloaded, test monkeypatching, etc.) so we don't hand
    out stale keys.
    """
    global _KEY_CYCLE, _CURRENT_POOL
    pool = tuple(settings.groq_key_pool)
    if not pool:
        raise GroqChatError(503, {"detail": "GROQ_API_KEY not configured"})
    if _KEY_CYCLE is None or pool != _CURRENT_POOL:
        _KEY_CYCLE = itertools.cycle(pool)
        _CURRENT_POOL = pool
    exclude = exclude or set()
    # At most one full lap; if every key is excluded, fall back to the first.
    for _ in range(len(pool)):
        candidate = next(_KEY_CYCLE)
        if candidate not in exclude:
            return candidate
    return pool[0]


async def chat_completion(
    *,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 60.0,
) -> str:
    try:
        from groq import AsyncGroq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GroqChatError(500, {"detail": f"groq SDK not installed: {exc}"}) from exc

    chosen_model = model or settings.groq_reasoning_model
    create_kwargs: dict = {
        "model": chosen_model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens or 4096,
    }
    if response_format is not None:
        create_kwargs["response_format"] = response_format
    # Groq gpt-oss models accept reasoning_effort ("low"|"medium"|"high") to
    # bound the CoT budget. Extraction tasks (verify/classify/summarize) use
    # "low" — they're deterministic pattern-matching, not deep reasoning —
    # which frees max_completion_tokens for actual output.
    if reasoning_effort is not None:
        create_kwargs["reasoning_effort"] = reasoning_effort

    pool_size = len(settings.groq_key_pool)
    tried: set[str] = set()
    last_err: GroqChatError | None = None

    # At most one attempt per configured key; on throttle (429/413) we try
    # the next key immediately rather than sleeping. Non-throttle errors
    # bubble up unchanged.
    for _ in range(max(1, pool_size)):
        key = _pick_key(exclude=tried)
        tried.add(key)
        client = AsyncGroq(api_key=key, timeout=timeout)
        async with time_llm("groq", chosen_model) as metric:
            try:
                completion = await client.chat.completions.create(**create_kwargs)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001  — Groq SDK raises various subclasses
                status_attr = getattr(exc, "status_code", None) or getattr(exc, "status", None)
                status_code = int(status_attr) if status_attr is not None else 502
                metric["status"] = status_code
                try:
                    body = (
                        getattr(exc, "body", None)
                        or getattr(exc, "response", None)
                        or {"error": str(exc)}
                    )
                except Exception:  # noqa: BLE001
                    body = {"error": str(exc)}
                last_err = GroqChatError(status_code, body)
                if status_code in _FALLTHROUGH_STATUSES and len(tried) < pool_size:
                    # Throttled on this key — try the next one before giving up.
                    continue
                raise last_err from exc

            try:
                content = completion.choices[0].message.content
            except (AttributeError, IndexError) as exc:
                metric["status"] = 502
                raise GroqChatError(502, {"detail": "unexpected Groq response shape"}) from exc

            return str(content or "")

    # Every key in the pool got throttled — surface the last error.
    assert last_err is not None
    raise last_err


async def stream_chat_completion(
    *,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> AsyncIterator[str]:
    """Yield text chunks from Groq as they arrive."""
    try:
        from groq import AsyncGroq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GroqChatError(500, {"detail": f"groq SDK not installed: {exc}"}) from exc

    chosen_model = model or settings.groq_reasoning_model
    # Streaming path picks one key per stream — mid-stream failover is
    # unsafe because tokens already yielded to the client can't be undone.
    client = AsyncGroq(api_key=_pick_key(), timeout=timeout)
    create_kwargs: dict = {
        "model": chosen_model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens or 4096,
        "stream": True,
    }

    async with time_llm("groq-stream", chosen_model) as metric:
        try:
            stream = await client.chat.completions.create(**create_kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            status_attr = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            status_code = int(status_attr) if status_attr is not None else 502
            metric["status"] = status_code
            body = (
                getattr(exc, "body", None) or getattr(exc, "response", None) or {"error": str(exc)}
            )
            raise GroqChatError(status_code, body) from exc

        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                continue
            if delta:
                yield str(delta)
