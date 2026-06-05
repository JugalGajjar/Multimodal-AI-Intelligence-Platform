"""Per-IP rate limiting for /auth/* endpoints.

Uses slowapi with Redis storage so multiple backend workers share counters.
Tests flip `rate_limit_enabled=False` so the unit suite stays hermetic.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def real_client_ip(request: Request) -> str:
    """Prefer X-Forwarded-For (set by the upstream proxy at HF Spaces /
    Vercel / etc.) over the direct peer address."""
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


def _storage_uri() -> str:
    if not settings.rate_limit_enabled:
        return "memory://"
    scheme = "async+rediss" if settings.redis_secure else "async+redis"
    auth = f":{settings.redis_password}@" if settings.redis_password else ""
    return f"{scheme}://{auth}{settings.redis_host}:{settings.redis_port}"


limiter = Limiter(
    key_func=real_client_ip,
    storage_uri=_storage_uri(),
    enabled=settings.rate_limit_enabled,
)
