"""Vision-language description of an image via OpenRouter.

Used at ingestion time to add semantic understanding (diagrams, UI screenshots,
charts) on top of raw OCR text. Falls back to a clear "vision-unavailable"
marker when the upstream model errors out so the rest of the pipeline still
runs (OCR text alone is still useful).
"""

import base64
import logging

from app.core.config import settings
from app.rag.openrouter import OpenRouterError, chat_completion

log = logging.getLogger("mmap.vision")

VISION_PROMPT = (
    "Describe this image in detail for someone who cannot see it. "
    "Note any visible text, diagrams, UI elements, charts, tables, "
    "or structural features. Be specific about labels, captions, axes, "
    "and relationships. Output plain prose only — no markdown headings."
)


class VisionError(Exception):
    """Raised when the vision model can't be reached."""


def _data_url(data: bytes, content_type: str) -> str:
    mime = (content_type or "image/png").split(";", 1)[0].strip().lower()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def describe_image_bytes(data: bytes, content_type: str) -> str:
    """Send the image to the configured OpenRouter vision model.

    Raises VisionError if the key is missing or upstream returns an error.
    """
    if not settings.openrouter_api_key:
        raise VisionError("OPENROUTER_API_KEY not configured")

    image_url = _data_url(data, content_type)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    try:
        return await chat_completion(
            messages=messages,
            model=settings.openrouter_vision_model,
            temperature=0.1,
        )
    except OpenRouterError as exc:
        log.warning("vision call failed: %s %s", exc.status_code, exc.body)
        raise VisionError(f"Vision model returned {exc.status_code}: {exc.body!r}") from exc
