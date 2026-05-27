"""Pure-Python recursive character chunker.

Tuned defaults: ~500 char chunks with 50 char overlap. Splits prefer paragraph,
then sentence, then word boundaries before falling back to hard char splits.
"""

from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50

# Order matters: try larger separators first.
_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    char_start: int
    char_end: int


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split *text* into character-bounded chunks with offsets back into source.

    `char_start`/`char_end` always refer to offsets in the **original** text.
    Whitespace at chunk boundaries is preserved; we never re-write content.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not text:
        return []

    chunks: list[Chunk] = []
    start = 0
    n = len(text)
    idx = 0

    while start < n:
        end = min(start + chunk_size, n)

        # Try to extend `end` backward to a natural boundary near the target.
        if end < n:
            best = _find_best_break(text, start, end)
            if best > start:
                end = best

        chunks.append(
            Chunk(
                index=idx,
                text=text[start:end],
                char_start=start,
                char_end=end,
            )
        )
        idx += 1

        if end >= n:
            break
        # Step forward by chunk_size - overlap, but never go backward.
        start = max(start + 1, end - chunk_overlap)

    return chunks


def _find_best_break(text: str, start: int, end: int) -> int:
    """Look for the latest natural separator inside [start, end)."""
    for sep in _SEPARATORS:
        if not sep:
            continue
        cut = text.rfind(sep, start, end)
        if cut > start:
            return cut + len(sep)
    return end
