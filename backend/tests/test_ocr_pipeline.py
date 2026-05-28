"""Unit tests for the extraction dispatch pipeline (no ML deps required)."""

from unittest.mock import AsyncMock, patch

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
    async def test_plain_text(self):
        assert await extract_text_from_bytes(b"hello world", "text/plain") == "hello world"

    async def test_markdown_text(self):
        assert await extract_text_from_bytes(b"# hi", "text/markdown; charset=utf-8") == "# hi"

    async def test_audio_dispatches_to_transcription(self):
        with patch(
            "app.transcription.whisper.transcribe_audio_bytes",
            return_value="hello from whisper",
        ) as transcribe:
            out = await extract_text_from_bytes(b"\x00\x01\x02\x03", "audio/mpeg")
            transcribe.assert_called_once()
            assert out == "hello from whisper"

    async def test_unknown_mime_raises(self):
        with pytest.raises(ValueError):
            await extract_text_from_bytes(b"", "application/x-msdownload")

    async def test_image_combines_ocr_and_vision(self):
        with (
            patch(
                "app.workers.ocr.engines.ocr_image_bytes",
                return_value="OCR-TEXT-HERE",
            ) as ocr,
            patch(
                "app.vision.describe.describe_image_bytes",
                new=AsyncMock(return_value="VISION-DESC-HERE"),
            ),
        ):
            out = await extract_text_from_bytes(b"\xff\xd8\xff\xe0", "image/jpeg")

        ocr.assert_called_once()
        assert "--- OCR text ---" in out
        assert "OCR-TEXT-HERE" in out
        assert "--- Visual description ---" in out
        assert "VISION-DESC-HERE" in out

    async def test_image_continues_when_vision_fails(self):
        from app.vision.describe import VisionError

        with (
            patch(
                "app.workers.ocr.engines.ocr_image_bytes",
                return_value="just-the-ocr",
            ),
            patch(
                "app.vision.describe.describe_image_bytes",
                new=AsyncMock(side_effect=VisionError("upstream down")),
            ),
        ):
            out = await extract_text_from_bytes(b"\xff", "image/png")

        assert "just-the-ocr" in out
        assert "Visual description" not in out

    async def test_image_continues_when_ocr_empty(self):
        with (
            patch(
                "app.workers.ocr.engines.ocr_image_bytes",
                return_value="",
            ),
            patch(
                "app.vision.describe.describe_image_bytes",
                new=AsyncMock(return_value="only the vision description"),
            ),
        ):
            out = await extract_text_from_bytes(b"\xff", "image/png")

        assert "only the vision description" in out
        assert "OCR text" not in out

    async def test_pdf_dispatches_to_pdf_path(self):
        with patch(
            "app.workers.ocr.pipeline.extract_text_from_pdf",
            return_value="PDF-MOCK",
        ) as fn:
            out = await extract_text_from_bytes(b"%PDF-1.4", "application/pdf")
            fn.assert_called_once()
            assert out == "PDF-MOCK"
