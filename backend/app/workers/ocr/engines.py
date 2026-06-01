"""OCR engines: RapidOCR primary, Tesseract fallback."""

import logging
from io import BytesIO

log = logging.getLogger("mmap.ocr")

# Heavy imports are guarded so the module loads in either container.
try:
    from rapidocr import RapidOCR  # type: ignore[import-not-found]

    RAPIDOCR_AVAILABLE = True
except Exception as _rapid_err:  # noqa: BLE001
    RAPIDOCR_AVAILABLE = False
    log.warning("RapidOCR unavailable: %r", _rapid_err)

try:
    import pytesseract  # type: ignore[import-not-found]
    from PIL import Image

    TESSERACT_AVAILABLE = True
except Exception as _tess_err:  # noqa: BLE001
    TESSERACT_AVAILABLE = False
    log.warning("Tesseract unavailable: %r", _tess_err)


_rapid_singleton = None


def _get_rapid():
    global _rapid_singleton
    if _rapid_singleton is None:
        _rapid_singleton = RapidOCR()
    return _rapid_singleton


def ocr_image_bytes_with_rapidocr(image_bytes: bytes) -> str:
    import numpy as np
    from PIL import Image

    pil = Image.open(BytesIO(image_bytes)).convert("RGB")
    arr = np.array(pil)
    result = _get_rapid()(arr)

    # `.txts` is a tuple of strings; result is None when nothing was detected.
    if result is None:
        return ""
    txts = getattr(result, "txts", None) or ()
    return "\n".join(t for t in txts if t)


def ocr_image_bytes_with_tesseract(image_bytes: bytes) -> str:
    pil = Image.open(BytesIO(image_bytes))
    return pytesseract.image_to_string(pil).strip()


def ocr_image_bytes(image_bytes: bytes) -> str:
    if RAPIDOCR_AVAILABLE:
        try:
            text = ocr_image_bytes_with_rapidocr(image_bytes)
            if text.strip():
                return text
            log.info("RapidOCR returned empty; falling back to Tesseract")
        except Exception as exc:  # noqa: BLE001
            log.warning("RapidOCR failed (%s); falling back to Tesseract", exc)
    if TESSERACT_AVAILABLE:
        return ocr_image_bytes_with_tesseract(image_bytes)
    raise RuntimeError("No OCR engine available (neither RapidOCR nor Tesseract installed)")
