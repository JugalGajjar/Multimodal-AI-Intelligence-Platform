"""Unit tests for the Groq Whisper wrapper. All network/SDK calls are mocked."""

import sys
import types
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.transcription import whisper


def test_raises_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")

    with pytest.raises(whisper.TranscriptionError) as exc:
        whisper.transcribe_audio_bytes(b"audio bytes")

    assert "not configured" in str(exc.value).lower()


def test_returns_transcript_text(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    # Build a fake `groq` module with a Groq class that mimics the SDK shape.
    fake_response = MagicMock(text="hello world")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_response
    fake_groq_class = MagicMock(return_value=fake_client)
    fake_module = types.ModuleType("groq")
    fake_module.Groq = fake_groq_class  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    out = whisper.transcribe_audio_bytes(b"binary audio data", filename="x.mp3")

    assert out == "hello world"
    fake_groq_class.assert_called_once_with(api_key="gsk_fake")
    call = fake_client.audio.transcriptions.create.call_args
    assert call.kwargs["model"] == settings.groq_whisper_model
    assert call.kwargs["response_format"] == "verbose_json"
    # `file` is a (filename, BytesIO) tuple
    fname, _buf = call.kwargs["file"]
    assert fname == "x.mp3"


def test_unexpected_response_shape_raises(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    fake_response = MagicMock(spec=[])  # no `text` attribute
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_response
    fake_module = types.ModuleType("groq")
    fake_module.Groq = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    with pytest.raises(whisper.TranscriptionError) as exc:
        whisper.transcribe_audio_bytes(b"x")

    assert "unexpected" in str(exc.value).lower()


def test_sdk_failure_wraps_in_transcription_error(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.side_effect = RuntimeError("upstream 500")
    fake_module = types.ModuleType("groq")
    fake_module.Groq = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    with pytest.raises(whisper.TranscriptionError) as exc:
        whisper.transcribe_audio_bytes(b"x")

    assert "upstream 500" in str(exc.value)


def test_strips_trailing_whitespace(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake")

    fake_response = MagicMock(text="  hi there  \n")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = fake_response
    fake_module = types.ModuleType("groq")
    fake_module.Groq = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", fake_module)

    assert whisper.transcribe_audio_bytes(b"x") == "hi there"
