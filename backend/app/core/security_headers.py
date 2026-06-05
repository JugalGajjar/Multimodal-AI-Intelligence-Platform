"""Defensive HTTP headers for every API response.

X-Frame-Options / CSP frame-ancestors are deliberately omitted — the API
returns JSON, not interactive HTML, so clickjacking doesn't apply, and
asserting DENY breaks the HF Spaces dashboard preview iframe. The Vercel
frontend (which actually serves HTML) sets those headers strictly itself.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        return response
