"""File-upload validation rules."""

import re

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "text/plain",
        "text/markdown",
    }
)

MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MiB

# Strip everything except letters, digits, `.`, `-`, `_`. Collapse repeats.
_FILENAME_BLOCK = re.compile(r"[^A-Za-z0-9._-]+")
_FILENAME_DUPDOTS = re.compile(r"\.{2,}")


def sanitize_filename(filename: str | None, fallback: str = "upload") -> str:
    """Strip path components and unsafe characters from an uploaded filename."""
    if not filename:
        return fallback

    base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    safe = _FILENAME_BLOCK.sub("_", base)
    safe = _FILENAME_DUPDOTS.sub(".", safe)
    safe = safe.strip("._-")
    return safe or fallback


def is_allowed_mime(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower() in ALLOWED_MIME_TYPES
