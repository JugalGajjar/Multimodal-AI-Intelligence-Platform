"""Audio transcription via Groq's hosted Whisper.

The Groq SDK is imported lazily so this module is safe to import in the API
container (which doesn't install the `worker` extras). Only the worker
actually calls `transcribe_audio_bytes`.
"""

from io import BytesIO

from app.core.config import settings


class TranscriptionError(Exception):
    """Raised when transcription cannot proceed (missing key, upstream error)."""


def transcribe_audio_bytes(
    data: bytes,
    *,
    filename: str = "audio",
    model: str | None = None,
    temperature: float = 0.0,
) -> str:
    """Send `data` to Groq Whisper and return the plain-text transcript.

    Raises `TranscriptionError` if the key is missing or Groq returns an error.
    """
    if not settings.groq_api_key:
        raise TranscriptionError("GROQ_API_KEY not configured")

    try:
        from groq import Groq  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TranscriptionError(f"groq SDK not installed (worker extras missing): {exc}") from exc

    client = Groq(api_key=settings.groq_api_key)
    try:
        result = client.audio.transcriptions.create(
            file=(filename, BytesIO(data)),
            model=model or settings.groq_whisper_model,
            response_format="verbose_json",
            temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"Groq Whisper call failed: {exc}") from exc

    text = getattr(result, "text", None)
    if not isinstance(text, str):
        raise TranscriptionError(f"unexpected Groq response shape: {result!r}")
    return text.strip()
