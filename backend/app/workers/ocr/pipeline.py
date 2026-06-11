"""Extract plain text from uploaded bytes by mime type."""

import asyncio
import contextlib
import logging
import os
from io import BytesIO
from tempfile import NamedTemporaryFile

from app.core.config import settings

log = logging.getLogger("mmap.extraction")

TEXT_MIME_PREFIXES = ("text/",)
IMAGE_MIME_PREFIXES = ("image/",)
PDF_MIME = "application/pdf"
AUDIO_MIME_PREFIXES = ("audio/",)
VIDEO_MIME_PREFIXES = ("video/",)

_VIDEO_MIME_TO_EXT: dict[str, str] = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}


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


async def _safe_describe_video_frames(frames: list[bytes], prompt: str) -> str:
    from app.video.describe import VideoVisionError, describe_video_frames

    try:
        return await describe_video_frames(frames, prompt=prompt)
    except VideoVisionError as exc:
        log.warning("video vision unavailable, transcript-only: %s", exc)
        return ""


def _safe_transcribe_video_audio(data: bytes, filename: str) -> str:
    from app.transcription.whisper import TranscriptionError, transcribe_audio_bytes

    try:
        return transcribe_audio_bytes(data, filename=filename)
    except TranscriptionError as exc:
        log.warning("video audio transcription failed: %s", exc)
        return ""


async def _extract_from_video(
    data: bytes,
    content_type: str,
    *,
    filename: str | None,
) -> str:
    # Sequential fused-RAG flow:
    #   1. Pull audio + frames in parallel (both are CPU/IO-bound, independent).
    #   2. Transcribe audio via Groq Whisper.
    #   3. Feed transcript INTO the Nemotron multimodal call as document
    #      context so the model can cross-reference what's said with what's
    #      shown — produces a richer description than concatenating two
    #      independent passes.
    from app.video.describe import build_video_description_prompt
    from app.workers.video.audio import extract_audio_track
    from app.workers.video.frames import extract_adaptive_frames, probe_video_duration

    mime = (content_type or "").lower().split(";", 1)[0].strip()
    ext = _VIDEO_MIME_TO_EXT.get(mime, "mp4")

    with NamedTemporaryFile(suffix=f".{ext}", delete=False) as tf:
        tf.write(data)
        path = tf.name

    try:
        # Fail fast on over-budget durations — cheaper than running
        # extraction + Whisper + Nemotron only to hit a downstream timeout.
        # Duration 0.0 means cv2 couldn't read metadata; let the sampler
        # below decide (it returns [] on the same condition).
        duration = await asyncio.to_thread(probe_video_duration, path)
        if duration > settings.video_max_duration_sec:
            max_minutes = settings.video_max_duration_sec // 60
            got_minutes = duration / 60
            raise ValueError(
                f"Video must be under {max_minutes} minutes "
                f"(got {got_minutes:.1f} minutes)."
            )

        frames, audio_bytes = await asyncio.gather(
            asyncio.to_thread(
                extract_adaptive_frames,
                path,
                max_frame_budget=settings.video_frame_budget,
                target_width=settings.video_target_width,
                jpeg_quality=settings.video_jpeg_quality,
            ),
            asyncio.to_thread(extract_audio_track, path),
        )

        transcript = ""
        if audio_bytes:
            if filename:
                stem = filename.rsplit(".", 1)[0] or "video"
                sent_name = f"{stem}.m4a"
            else:
                sent_name = "video.m4a"
            transcript = await asyncio.to_thread(
                _safe_transcribe_video_audio, audio_bytes, sent_name
            )

        description = ""
        if frames:
            description = await _safe_describe_video_frames(
                frames, prompt=build_video_description_prompt(transcript)
            )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)

    # Index transcript verbatim (exact dialogue retrieval) plus the fused
    # description (visual content retrieval). Both flow to chunking/embedding,
    # graph extraction, and summary downstream.
    parts: list[str] = []
    if transcript.strip():
        parts.append(f"--- Audio transcript ---\n{transcript.strip()}")
    if description.strip():
        parts.append(f"--- Visual description ---\n{description.strip()}")
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

    if mime.startswith(VIDEO_MIME_PREFIXES):
        return await _extract_from_video(data, content_type, filename=filename)

    if mime.startswith(AUDIO_MIME_PREFIXES):
        from app.transcription.whisper import transcribe_audio_bytes

        ext = _AUDIO_MIME_TO_EXT.get(mime, "wav")
        sent_name = filename or f"audio.{ext}"
        return await asyncio.to_thread(transcribe_audio_bytes, data, filename=sent_name)

    raise ValueError(f"Unsupported MIME for OCR: {mime!r}")
