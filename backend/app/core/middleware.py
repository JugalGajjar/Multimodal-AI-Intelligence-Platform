"""Request-ID propagation and HTTP metrics middleware."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import request_id_var
from app.core.metrics import http_request_duration_seconds, http_requests_total

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Honor an inbound X-Request-ID or mint a new one; expose on response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    """Record per-route count and latency.

    `path` uses the route template (e.g. /documents/{document_id}) when known
    so cardinality stays bounded; falls back to the raw path otherwise.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        # Skip noisy probes / docs from histogram labels.
        if path in {"/metrics", "/docs", "/redoc", "/openapi.json"}:
            return response

        method = request.method
        status = str(response.status_code)
        http_requests_total.labels(method=method, path=path, status_code=status).inc()
        http_request_duration_seconds.labels(method=method, path=path).observe(duration)
        return response
