"""OCR engines. Paddle is primary; Tesseract is fallback.

All ML/heavy imports are wrapped in try/except so the module can be imported
in environments where Paddle isn't available — we just disable that engine.
"""

import logging
from io import BytesIO

log = logging.getLogger("mmap.ocr")

# --- Paddle (best-effort import) ----------------------------------------
try:
    from paddleocr import PaddleOCR  # type: ignore[import-not-found]

    PADDLE_AVAILABLE = True
except Exception as _paddle_err:  # noqa: BLE001
    PADDLE_AVAILABLE = False
    _PADDLE_IMPORT_ERROR = repr(_paddle_err)
    log.warning("PaddleOCR unavailable: %s", _PADDLE_IMPORT_ERROR)

# --- Tesseract (best-effort) ---------------------------------------------
try:
    import pytesseract  # type: ignore[import-not-found]
    from PIL import Image

    TESSERACT_AVAILABLE = True
except Exception as _tess_err:  # noqa: BLE001
    TESSERACT_AVAILABLE = False
    log.warning("Tesseract unavailable: %s", _tess_err)


_paddle_singleton = None


def _get_paddle():
    global _paddle_singleton
    if _paddle_singleton is None:
        _paddle_singleton = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return _paddle_singleton


def ocr_image_bytes_with_paddle(image_bytes: bytes) -> str:
    import numpy as np
    from PIL import Image

    pil = Image.open(BytesIO(image_bytes)).convert("RGB")
    arr = np.array(pil)
    result = _get_paddle().ocr(arr, cls=True)

    lines: list[str] = []
    if not result or result[0] is None:
        return ""
    for line in result[0]:
        # line = [box_pts, (text, conf)]
        if len(line) >= 2 and isinstance(line[1], tuple | list):
            text = line[1][0]
            if text:
                lines.append(str(text))
    return "\n".join(lines)


def ocr_image_bytes_with_tesseract(image_bytes: bytes) -> str:
    pil = Image.open(BytesIO(image_bytes))
    return pytesseract.image_to_string(pil).strip()


def ocr_image_bytes(image_bytes: bytes) -> str:
    """Try Paddle first, fall back to Tesseract."""
    if PADDLE_AVAILABLE:
        try:
            text = ocr_image_bytes_with_paddle(image_bytes)
            if text.strip():
                return text
            log.info("Paddle returned empty; falling back to Tesseract")
        except Exception as exc:  # noqa: BLE001
            log.warning("Paddle OCR failed (%s); falling back to Tesseract", exc)
    if TESSERACT_AVAILABLE:
        return ocr_image_bytes_with_tesseract(image_bytes)
    raise RuntimeError("No OCR engine available (neither PaddleOCR nor Tesseract installed)")
