"""Lockout module — exercises the failure-silent behaviour without Redis.

We only test the public-facing shape (silent-fail returns False/0) because
the real counter logic needs a live Redis; that's covered in integration.
"""

from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import RedisError

from app.auth import lockout


class TestLockoutFailsSilent:
    @pytest.mark.asyncio
    async def test_is_locked_out_returns_false_when_redis_unreachable(self):
        async def boom(*_, **__):
            raise RedisError("connection refused")

        with patch.object(lockout, "_client") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(side_effect=boom)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            locked, ttl = await lockout.is_locked_out("alice@example.com")

        assert locked is False
        assert ttl == 0

    @pytest.mark.asyncio
    async def test_record_failed_login_returns_zero_when_redis_unreachable(self):
        async def boom(*_, **__):
            raise RedisError("connection refused")

        with patch.object(lockout, "_client") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(side_effect=boom)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            count = await lockout.record_failed_login("alice@example.com")

        assert count == 0

    @pytest.mark.asyncio
    async def test_clear_failed_logins_returns_none_when_redis_unreachable(self):
        async def boom(*_, **__):
            raise RedisError("connection refused")

        with patch.object(lockout, "_client") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(side_effect=boom)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Just ensure it doesn't raise.
            await lockout.clear_failed_logins("alice@example.com")


class TestKeyNamespacing:
    def test_email_is_lowercased(self):
        assert lockout._key("Alice@Example.com") == "auth:lockout:alice@example.com"

    def test_key_prefix(self):
        assert lockout._key("a@b.com").startswith("auth:lockout:")
