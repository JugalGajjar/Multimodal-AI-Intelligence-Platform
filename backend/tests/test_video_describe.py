"""Unit tests for the video vision-language wrapper. OpenRouter is mocked."""

import base64
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.rag.openrouter import OpenRouterError
from app.video import describe as video
from app.video.describe import VIDEO_PROMPT, build_video_description_prompt


@pytest.fixture(autouse=True)
def _video_settings(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "fake-key")
    monkeypatch.setattr(settings, "openrouter_video_model", "vendor/video-mock:free")
    monkeypatch.setattr(settings, "video_include_reasoning", False)


async def test_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    with pytest.raises(video.VideoVisionError):
        await video.describe_video_frames([b"frame"])


async def test_empty_frames_returns_empty_without_calling_api():
    with patch.object(video, "chat_completion", new=AsyncMock()) as mock:
        out = await video.describe_video_frames([])

    assert out == ""
    mock.assert_not_called()


async def test_payload_shape_matches_prototype():
    frames = [b"frame-a", b"frame-b", b"frame-c"]

    with patch.object(
        video, "chat_completion", new=AsyncMock(return_value="a person walks past a car")
    ) as fake:
        out = await video.describe_video_frames(frames)

    assert out == "a person walks past a car"
    kwargs = fake.call_args.kwargs
    assert kwargs["model"] == "vendor/video-mock:free"
    assert kwargs["temperature"] == 0.1
    assert kwargs["timeout"] == 180.0
    assert kwargs["extra_body"] is None

    msgs = kwargs["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    # N image_url parts followed by a single trailing text part.
    assert len(content) == len(frames) + 1

    for i, raw in enumerate(frames):
        part = content[i]
        assert part["type"] == "image_url"
        url = part["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        assert url.endswith(base64.b64encode(raw).decode("ascii"))

    assert content[-1] == {"type": "text", "text": VIDEO_PROMPT}


async def test_include_reasoning_threaded_through(monkeypatch):
    monkeypatch.setattr(settings, "video_include_reasoning", True)

    with patch.object(video, "chat_completion", new=AsyncMock(return_value="ok")) as fake:
        await video.describe_video_frames([b"f"])

    assert fake.call_args.kwargs["extra_body"] == {"include_reasoning": True}


async def test_custom_prompt_overrides_default():
    with patch.object(video, "chat_completion", new=AsyncMock(return_value="ok")) as fake:
        await video.describe_video_frames([b"f"], prompt="How many people?")

    content = fake.call_args.kwargs["messages"][0]["content"]
    assert content[-1] == {"type": "text", "text": "How many people?"}


async def test_openrouter_error_is_wrapped():
    err = OpenRouterError(429, {"detail": "rate limited"})

    with (
        patch.object(video, "chat_completion", new=AsyncMock(side_effect=err)),
        pytest.raises(video.VideoVisionError) as exc_info,
    ):
        await video.describe_video_frames([b"f"])

    assert "429" in str(exc_info.value)


def test_build_prompt_falls_back_when_transcript_empty():
    assert build_video_description_prompt("") == VIDEO_PROMPT
    assert build_video_description_prompt("   \n\t  ") == VIDEO_PROMPT


def test_build_prompt_embeds_transcript_as_document_context():
    prompt = build_video_description_prompt("She points at the chart and says hello.")
    assert "DOCUMENT CONTEXT: EXTRACTED AUDIO TRANSCRIPT" in prompt
    assert "Cross-reference" in prompt
    assert "She points at the chart and says hello." in prompt
    # Transcript is inlined verbatim, not summarized.
    assert prompt.endswith("She points at the chart and says hello.")
