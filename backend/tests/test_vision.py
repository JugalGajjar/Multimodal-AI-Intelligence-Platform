"""Unit tests for the vision-language wrapper. OpenRouter is mocked."""

import base64
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.rag.openrouter import OpenRouterError
from app.vision import describe as vision


def test_data_url_is_correctly_base64_encoded():
    raw = b"\x89PNG\r\n\x1a\n" + b"PAYLOAD"
    url = vision._data_url(raw, "image/png")

    assert url.startswith("data:image/png;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == raw


def test_data_url_normalises_mime():
    url = vision._data_url(b"x", "Image/JPEG; charset=binary")

    assert url.startswith("data:image/jpeg;base64,")


async def test_describe_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    with pytest.raises(vision.VisionError):
        await vision.describe_image_bytes(b"fake", "image/png")


async def test_describe_returns_chat_completion_text(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    monkeypatch.setattr(settings, "openrouter_vision_model", "vendor/vision-mock:free")

    with patch(
        "app.vision.describe.chat_completion",
        new=AsyncMock(return_value="a green chart with three bars"),
    ) as fake:
        out = await vision.describe_image_bytes(b"img-bytes", "image/png")

    assert out == "a green chart with three bars"
    args = fake.call_args.kwargs
    assert args["model"] == "vendor/vision-mock:free"
    # Single user message with text + image_url content parts
    msgs = args["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    parts = msgs[0]["content"]
    assert any(p["type"] == "text" for p in parts)
    assert any(p["type"] == "image_url" for p in parts)
    img_part = next(p for p in parts if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


async def test_describe_wraps_openrouter_errors_in_vision_error(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    with (
        patch(
            "app.vision.describe.chat_completion",
            new=AsyncMock(side_effect=OpenRouterError(429, {"detail": "rate limited"})),
        ),
        pytest.raises(vision.VisionError) as exc,
    ):
        await vision.describe_image_bytes(b"x", "image/png")

    assert "429" in str(exc.value)


async def test_describe_uses_low_temperature(monkeypatch):
    """Vision descriptions should be deterministic, not creative."""
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")

    with patch(
        "app.vision.describe.chat_completion",
        new=AsyncMock(return_value="ok"),
    ) as fake:
        await vision.describe_image_bytes(b"x", "image/jpeg")

    assert fake.call_args.kwargs["temperature"] <= 0.2
