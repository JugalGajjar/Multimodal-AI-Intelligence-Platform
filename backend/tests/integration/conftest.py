"""
Integration tests run against a live docker-compose stack.

They are marked with @pytest.mark.integration and skipped by default unless
the user runs `pytest -m integration` (or `-m "integration or not integration"`).

Each test connects to the host-published port of the service so we do not
require pytest to run inside docker.
"""

import asyncio
import socket
import urllib.error
import urllib.request

import pytest

# Strong password used by every integration test that registers a user —
# meets the validator's class/length/forbidden-substring rules.
STRONG_PASSWORD = "StrongP@ss1"

pytestmark = pytest.mark.integration


def can_connect(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def require_stack_up():
    """Skip the entire suite if the stack is unreachable on the standard ports."""
    if not can_connect("127.0.0.1", 8000):
        pytest.skip(
            "docker compose stack not up on localhost (backend port 8000 unreachable)",
            allow_module_level=True,
        )


def http_get(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def mark_user_verified(email: str) -> None:
    """Flip is_verified=true directly in Postgres so a sync test can /login
    without going through the email-code flow. Uses a fresh event loop —
    only safe from sync tests."""
    from sqlalchemy import update

    from app.auth.models import User
    from app.db.session import async_session_maker

    async def _run() -> None:
        async with async_session_maker() as session:
            await session.execute(update(User).where(User.email == email).values(is_verified=True))
            await session.commit()

    asyncio.run(_run())
