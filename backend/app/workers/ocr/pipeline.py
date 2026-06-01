"""Extract plain text from uploaded bytes by mime type."""

import asyncio
import logging
from io import BytesIO

log = logging.getLogger("mmap.extraction")

TEXT_MIME_PREFIXES = ("text/",)
IMAGE_MIME_PREFIXES = ("image/",)
PDF_MIME = "application/pdf"
AUDIO_MIME_PREFIXES = ("audio/",)


def decode_text_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def extract_text_from_pdf(data: bytes) -> str:
    # Rasterize each page then OCR. Synchronous; CPU-heavy.
    from pdf2image import convert_from_bytes  # type: ignore[import-not-found]

    from app.workers.ocr.engines import ocr_image_bytes

    images = convert_from_bytes(data, dpi=200)
    parts: list[str] = []
    for i, pil_image in enumerate(images, start=1):
        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        text = ocr_image_bytes(buf.getvalue())
        if text.strip():
            parts.append(f"--- page {i} ---\n{text}")
    return "\n\n".join(parts)


_AUDIO_MIME_TO_EXT: dict[str, str] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
}


async def _safe_describe_image(data: bytes, content_type: str) -> str:
    # Degrade to empty string on vision errors so OCR text alone can flow through.
    from app.vision.describe import VisionError, describe_image_bytes

    try:
        return await describe_image_bytes(data, content_type)
    except VisionError as exc:
        log.warning("vision unavailable, OCR-only: %s", exc)
        return ""


async def _extract_from_image(data: bytes, content_type: str) -> str:
    from app.workers.ocr.engines import ocr_image_bytes

    ocr_text, vision_text = await asyncio.gather(
        asyncio.to_thread(ocr_image_bytes, data),
        _safe_describe_image(data, content_type),
    )

    parts: list[str] = []
    if ocr_text.strip():
        parts.append(f"--- OCR text ---\n{ocr_text.strip()}")
    if vision_text.strip():
        parts.append(f"--- Visual description ---\n{vision_text.strip()}")
    return "\n\n".join(parts)


async def extract_text_from_bytes(
    data: bytes,
    content_type: str,
    *,
    filename: str | None = None,
) -> str:
    # `filename` is forwarded to Groq Whisper (it validates the extension);
    # we synthesize one from the mime when the upload didn't include it.
    mime = (content_type or "").lower().split(";", 1)[0].strip()

    if mime.startswith(TEXT_MIME_PREFIXES):
        return decode_text_bytes(data)

    if mime == PDF_MIME:
        return await asyncio.to_thread(extract_text_from_pdf, data)

    if mime.startswith(IMAGE_MIME_PREFIXES):
        return await _extract_from_image(data, content_type)

    if mime.startswith(AUDIO_MIME_PREFIXES):
        from app.transcription.whisper import transcribe_audio_bytes

        ext = _AUDIO_MIME_TO_EXT.get(mime, "wav")
        sent_name = filename or f"audio.{ext}"
        return await asyncio.to_thread(transcribe_audio_bytes, data, filename=sent_name)

    raise ValueError(f"Unsupported MIME for OCR: {mime!r}")
