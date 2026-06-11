"""Vision-language description of a video via OpenRouter, given pre-extracted frames."""

import base64
import logging

from app.core.config import settings
from app.rag.openrouter import OpenRouterError, chat_completion

log = logging.getLogger("mmap.video")

VIDEO_PROMPT = (
    "Describe this video in detail for someone who cannot see it. "
    "Summarize the sequence of events, visible text, people, objects, "
    "scene transitions, and any on-screen UI, diagrams, or charts. "
    "Note ordering and approximate timing where it matters. Be specific "
    "about labels, captions, and relationships. Output plain prose only "
    "— no markdown headings."
)


def build_video_description_prompt(transcript: str) -> str:
    """Compose the multimodal prompt. When `transcript` is non-empty, embed
    it as document context so Nemotron can cross-reference frames against
    spoken dialogue — fusion produces a noticeably richer description than
    running the two modalities independently and concatenating outputs."""
    if not transcript.strip():
        return VIDEO_PROMPT

    return (
        "You are an expert video analyst. You are given a sequential array "
        "of frames from a video (attached above) and a full transcript of "
        "the spoken audio (below). Cross-reference both modalities to "
        "produce a comprehensive description for someone who cannot watch "
        "the video.\n\n"
        "Align spoken statements to the visual moments where they occur. "
        "Name visible people and objects, summarize scene transitions, and "
        "quote on-screen text or UI labels exactly. Output plain prose only "
        "— no markdown headings.\n\n"
        "==================================================\n"
        "DOCUMENT CONTEXT: EXTRACTED AUDIO TRANSCRIPT\n"
        "==================================================\n"
        f"{transcript.strip()}"
    )


class VideoVisionError(Exception):
    pass


def _jpeg_data_url(frame: bytes) -> str:
    b64 = base64.b64encode(frame).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def describe_video_frames(frames: list[bytes], prompt: str | None = None) -> str:
    if not settings.openrouter_api_key:
        raise VideoVisionError("OPENROUTER_API_KEY not configured")
    if not frames:
        return ""

    content: list[dict] = [
        {"type": "image_url", "image_url": {"url": _jpeg_data_url(f)}} for f in frames
    ]
    content.append({"type": "text", "text": prompt or VIDEO_PROMPT})

    extra_body = {"include_reasoning": True} if settings.video_include_reasoning else None

    try:
        return await chat_completion(
            messages=[{"role": "user", "content": content}],
            model=settings.openrouter_video_model,
            temperature=0.1,
            timeout=180.0,
            extra_body=extra_body,
        )
    except OpenRouterError as exc:
        log.warning("video vision call failed: %s %s", exc.status_code, exc.body)
        raise VideoVisionError(f"Video model returned {exc.status_code}: {exc.body!r}") from exc
