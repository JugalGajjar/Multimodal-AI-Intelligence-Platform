"""JSON logging configured to carry per-request correlation IDs."""

from __future__ import annotations

import logging
from contextvars import ContextVar

from opentelemetry import trace
from pythonjsonlogger.json import JsonFormatter

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


class CorrelationFilter(logging.Filter):
    """Attach correlation IDs from contextvars and the current span onto records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            # Format ids as in the OTel spec — zero-padded lowercase hex.
            record.trace_id = f"{ctx.trace_id:032x}"
            record.span_id = f"{ctx.span_id:016x}"
        else:
            record.trace_id = None
            record.span_id = None
        return True


def configure_logging(level: str = "INFO") -> None:
    """Replace the root handler with a JSON one. Idempotent."""
    formatter = JsonFormatter(
        "{asctime} {levelname} {name} {message} {request_id} {user_id} {trace_id} {span_id}",
        style="{",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationFilter())

    root = logging.getLogger()
    # Replace any handlers (uvicorn / pytest installs its own).
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn's named loggers shouldn't double-emit through their own handlers.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
