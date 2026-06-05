from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.email import client as email_client
from app.email.templates import password_reset_email, verification_email


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_skips_when_key_unset(self, monkeypatch):
        # Patch the settings object the client module already captured —
        # other tests reload app.core.config and rebind the singleton.
        monkeypatch.setattr(email_client.settings, "resend_api_key", "")
        result = await email_client.send_email(to="a@b.com", subject="x", text="y")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_on_200(self, monkeypatch):
        monkeypatch.setattr(email_client.settings, "resend_api_key", "test-key")
        mock_resp = httpx.Response(200, json={"id": "abc"})

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            result = await email_client.send_email(to="a@b.com", subject="x", text="y")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_4xx(self, monkeypatch):
        monkeypatch.setattr(email_client.settings, "resend_api_key", "test-key")
        mock_resp = httpx.Response(403, text="forbidden")

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            result = await email_client.send_email(to="a@b.com", subject="x", text="y")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_network_error(self, monkeypatch):
        monkeypatch.setattr(email_client.settings, "resend_api_key", "test-key")

        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.ConnectError("no route")),
        ):
            result = await email_client.send_email(to="a@b.com", subject="x", text="y")
        assert result is False


class TestEmailTemplates:
    def test_verification_includes_code(self):
        subject, body = verification_email("ABCD1234")
        assert "ABCD1234" in body
        assert "verification" in subject.lower()
        assert "24 hours" in body

    def test_password_reset_includes_code(self):
        subject, body = password_reset_email("XYZ98765")
        assert "XYZ98765" in body
        assert "password reset" in subject.lower()
        assert "1 hour" in body
        assert "only be used once" in body
