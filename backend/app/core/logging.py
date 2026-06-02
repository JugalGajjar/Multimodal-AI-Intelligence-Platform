"""JSON logging configured to carry per-request correlation IDs."""

from __future__ import annotations

import logging
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


class CorrelationFilter(logging.Filter):
    """Attach `request_id` / `user_id` from contextvars onto every log record.

    Without this, the JSON formatter would only see fields explicitly passed
    via `extra=`. Anchoring the IDs in a contextvar means downstream code
    doesn't have to thread them through every log call.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Replace the root handler with a JSON one. Idempotent."""
    formatter = JsonFormatter(
        "{asctime} {levelname} {name} {message} {request_id} {user_id}",
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
