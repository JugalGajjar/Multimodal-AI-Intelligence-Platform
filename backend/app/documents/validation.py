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
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "text/plain",
        "text/markdown",
        # Modern Office XML formats. Legacy .doc / .ppt are out of scope —
        # they need LibreOffice / antiword and add real image size + flakiness.
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)

MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MiB

# Strip everything except letters, digits, `.`, `-`, `_`. Collapse repeats.
_FILENAME_BLOCK = re.compile(r"[^A-Za-z0-9._-]+")
_FILENAME_DUPDOTS = re.compile(r"\.{2,}")


def sanitize_filename(filename: str | None, fallback: str = "upload") -> str:
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
