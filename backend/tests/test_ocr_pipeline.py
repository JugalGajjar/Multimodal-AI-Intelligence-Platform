"""Unit tests for the OCR dispatch pipeline (no ML deps required)."""

from unittest.mock import patch

import pytest

from app.workers.ocr.pipeline import (
    decode_text_bytes,
    extract_text_from_bytes,
)


class TestDecodeTextBytes:
    def test_decodes_utf8(self):
        assert decode_text_bytes(b"hello") == "hello"

    def test_handles_invalid_utf8_via_replacement(self):
        # 0xff is not valid in UTF-8 — must not raise.
        out = decode_text_bytes(b"hello \xff world")
        assert "hello" in out and "world" in out


class TestExtractTextFromBytes:
    def test_plain_text(self):
        assert extract_text_from_bytes(b"hello world", "text/plain") == "hello world"

    def test_markdown_text(self):
        assert extract_text_from_bytes(b"# hi", "text/markdown; charset=utf-8") == "# hi"

    def test_audio_returns_empty_placeholder(self):
        # Audio handling is Phase 3 (Groq Whisper) — return empty for now.
        assert extract_text_from_bytes(b"\x00\x01", "audio/mpeg") == ""

    def test_unknown_mime_raises(self):
        with pytest.raises(ValueError):
            extract_text_from_bytes(b"", "application/x-msdownload")

    def test_image_dispatches_to_engine(self):
        with patch("app.workers.ocr.engines.ocr_image_bytes", return_value="MOCK-TEXT") as engine:
            out = extract_text_from_bytes(b"\xff\xd8\xff\xe0", "image/jpeg")
            engine.assert_called_once()
            assert out == "MOCK-TEXT"

    def test_pdf_dispatches_to_pdf_path(self):
        with patch(
            "app.workers.ocr.pipeline.extract_text_from_pdf",
            return_value="PDF-MOCK",
        ) as fn:
            out = extract_text_from_bytes(b"%PDF-1.4", "application/pdf")
            fn.assert_called_once()
            assert out == "PDF-MOCK"
