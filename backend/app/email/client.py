"""Thin wrapper around the Resend HTTP API.

Resend's Python SDK pulls in extra deps; the REST surface is one POST so we
hit it directly with httpx. Logs but doesn't raise — a failed email shouldn't
500 the calling endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT_SEC = 10.0


class EmailNotConfiguredError(RuntimeError):
    """Raised at startup time only — caller catches and degrades gracefully."""


async def send_email(*, to: str, subject: str, text: str) -> bool:
    """Send a plain-text email via Resend. Returns True on success."""
    if not settings.resend_api_key:
        log.warning("email send skipped (RESEND_API_KEY unset): to=%s", to)
        return False

    payload: dict[str, Any] = {
        "from": settings.resend_from_email,
        "to": [to],
        "subject": subject,
        "text": text,
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.post(_RESEND_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error(
                "resend send failed: status=%s body=%s to=%s",
                resp.status_code,
                resp.text[:300],
                to,
            )
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("resend HTTP error: %s to=%s", exc, to)
        return False
