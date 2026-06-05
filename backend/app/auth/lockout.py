"""Per-account login lockout.

Tracks failed /auth/login attempts in Redis with an expiring counter.
Past the threshold, the account is locked until the window expires —
returns a 429 with the time remaining so the UI can surface it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis_async

from app.core.config import settings

log = logging.getLogger(__name__)


def _key(email: str) -> str:
    return f"auth:lockout:{email.lower()}"


@asynccontextmanager
async def _client() -> AsyncIterator[redis_async.Redis]:
    client = redis_async.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        ssl=settings.redis_secure,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        await client.aclose()


async def is_locked_out(email: str) -> tuple[bool, int]:
    """Returns (locked, seconds_until_unlock). Silent on Redis failure."""
    try:
        async with _client() as r:
            count = await r.get(_key(email))
            if count is None or int(count) < settings.auth_lockout_threshold:
                return False, 0
            ttl = await r.ttl(_key(email))
            return True, max(0, int(ttl))
    except redis_async.RedisError as exc:
        log.warning("lockout check failed: %s", exc)
        return False, 0


async def record_failed_login(email: str) -> int:
    """Increment the per-email fail counter. Returns the new count."""
    try:
        async with _client() as r:
            key = _key(email)
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, settings.auth_lockout_window_sec)
            return int(count)
    except redis_async.RedisError as exc:
        log.warning("lockout incr failed: %s", exc)
        return 0


async def clear_failed_logins(email: str) -> None:
    try:
        async with _client() as r:
            await r.delete(_key(email))
    except redis_async.RedisError as exc:
        log.warning("lockout clear failed: %s", exc)
