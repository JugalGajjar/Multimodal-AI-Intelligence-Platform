"""High-level OCR pipeline: bytes + mime → plain text."""

import logging
from io import BytesIO

log = logging.getLogger("mmap.ocr")

TEXT_MIME_PREFIXES = ("text/",)
IMAGE_MIME_PREFIXES = ("image/",)
PDF_MIME = "application/pdf"
AUDIO_MIME_PREFIXES = ("audio/",)


def decode_text_bytes(data: bytes) -> str:
    """Decode a text/* upload, tolerating non-UTF-8 with a replacement strategy."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def extract_text_from_pdf(data: bytes) -> str:
    """Rasterize each PDF page and OCR it."""
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


def extract_text_from_bytes(data: bytes, content_type: str) -> str:
    """Dispatch to the right extractor based on MIME type."""
    mime = (content_type or "").lower().split(";", 1)[0].strip()

    if mime.startswith(TEXT_MIME_PREFIXES):
        return decode_text_bytes(data)

    if mime == PDF_MIME:
        return extract_text_from_pdf(data)

    if mime.startswith(IMAGE_MIME_PREFIXES):
        from app.workers.ocr.engines import ocr_image_bytes

        return ocr_image_bytes(data)

    if mime.startswith(AUDIO_MIME_PREFIXES):
        # Audio transcription lands in Phase 3 (Groq Whisper).
        return ""

    raise ValueError(f"Unsupported MIME for OCR: {mime!r}")
