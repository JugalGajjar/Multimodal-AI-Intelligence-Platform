"""Section-aware chunker with a recursive-character fallback.

Design:
  1. Scan the source text for heading-like lines (all-caps headings, markdown
     headings, our own `--- page N ---` / `--- slide N ---` markers from the
     PDF and PowerPoint extractors, numbered sections like "1. Introduction").
  2. Split at those boundaries — a section is a heading plus the body text
     that follows it until the next heading.
  3. For each section, produce chunks with the *heading prepended* so
     retrieval sees "RESEARCH PUBLICATIONS\\nRSAT: ..." rather than an
     orphaned bullet the reader can't place. When the section body is longer
     than the target chunk size, split recursively on paragraph → sentence →
     word → char boundaries (the old chunker's behaviour).

Tuned defaults: ~500 char chunks with 50 char overlap. Same story as before;
the outer API `chunk_text(text) -> list[Chunk]` is unchanged so callers keep
working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
# Chunks with less alphanumeric content than this are dropped at ingest;
# they're typically OCR/PDF noise and rank highly on character-level overlap.
MIN_MEANINGFUL_ALNUM_CHARS = 80

# Order matters: try larger separators first.
_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

# Any match → line is treated as a heading.
_HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Markdown ATX headings ("#", "##", ..., "######").
    re.compile(r"^#{1,6}\s+\S"),
    # Our own extractor markers (PDF page markers, PPTX slide markers).
    re.compile(r"^-{3}\s*(page|slide)\s+\d+\s*-{3}\s*$", re.IGNORECASE),
    # Numbered sections like "1. Introduction", "2.1 Method". Short lines
    # only so we don't accidentally match numbered bullet points.
    re.compile(r"^\d+(\.\d+)*\.?\s+[A-Z][^\n]{0,79}$"),
)

# Heuristic: an all-caps line that looks like a heading. Length + alpha
# constraints keep us from matching "OK." or an entire capsed paragraph.
_ALL_CAPS_HEADING_RE = re.compile(
    r"^[A-Z0-9][A-Z0-9\s\-&:,/()'.]{2,79}$",
)


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    for pat in _HEADING_PATTERNS:
        if pat.match(stripped):
            return True
    if _ALL_CAPS_HEADING_RE.match(stripped):
        # Need at least 3 real letters; regex already forbids lowercase.
        alpha = sum(1 for c in stripped if c.isalpha())
        if alpha >= 3:
            return True
    return False


@dataclass(frozen=True)
class _Section:
    heading: str  # empty when no heading (leading body text before any heading)
    content: str  # body text under the heading (heading line not included)
    source_start: int  # offset of the section's first character in the source
    source_end: int  # exclusive end offset in the source


def _parse_sections(text: str) -> list[_Section]:
    """Split `text` into (heading, content) sections. When no headings are
    detected the whole text becomes a single anonymous section."""
    lines_with_offset: list[tuple[int, str]] = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        lines_with_offset.append((offset, raw))
        offset += len(raw)

    sections: list[_Section] = []
    current_heading = ""
    current_start = 0
    body_parts: list[str] = []

    def flush(end_offset: int) -> None:
        content = "".join(body_parts).strip("\n")
        if current_heading or content.strip():
            sections.append(
                _Section(
                    heading=current_heading,
                    content=content,
                    source_start=current_start,
                    source_end=end_offset,
                )
            )

    started = False
    for line_offset, line in lines_with_offset:
        if _is_heading(line):
            flush(line_offset)
            current_heading = line.strip()
            current_start = line_offset
            body_parts = []
            started = True
        else:
            if not started and not body_parts:
                current_start = line_offset
                started = True
            body_parts.append(line)

    flush(offset)
    return sections


# ---------------------------------------------------------------------------
# Chunk model + public API
# ---------------------------------------------------------------------------


def is_meaningful(text: str) -> bool:
    """A chunk is meaningful if it has enough alphanumeric content to be
    worth indexing. Cheap filter that drops fragments like 'rs' or 'rmat [1'."""
    return sum(1 for c in text if c.isalnum()) >= MIN_MEANINGFUL_ALNUM_CHARS


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
    """Split `text` into chunks that respect section structure.

    Each returned chunk carries the section's heading prepended (when one was
    detected) so retrieval sees "PUBLICATIONS\\nRSAT: ..." instead of an
    orphan bullet the model can't place. Long sections still get sub-split
    recursively on paragraph → sentence → word → char boundaries.

    `char_start` / `char_end` on the returned Chunks refer to offsets in the
    **original** text (pointing at the section body; the heading prefix is
    metadata prepended to `text`, not part of the source range).
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not text:
        return []

    sections = _parse_sections(text)

    chunks: list[Chunk] = []
    idx = 0

    for section in sections:
        prefix = f"{section.heading}\n" if section.heading else ""
        # Reserve room for the heading prefix inside the chunk size budget.
        available = max(chunk_size - len(prefix), 100)
        body_source_offset = section.source_start + (
            len(section.heading) + 1 if section.heading else 0
        )
        for body_text, body_start, body_end in _split_body(
            section.content, available, chunk_overlap
        ):
            source_start = body_source_offset + body_start
            source_end = source_start + (body_end - body_start)
            chunks.append(
                Chunk(
                    index=idx,
                    text=prefix + body_text,
                    char_start=source_start,
                    char_end=source_end,
                )
            )
            idx += 1

    return chunks


def _split_body(body: str, chunk_size: int, chunk_overlap: int) -> list[tuple[str, int, int]]:
    """Recursive-character splitter for the *body* of a section. Returns
    (text, start, end) tuples where start/end are offsets inside `body`."""
    if not body:
        return []

    out: list[tuple[str, int, int]] = []
    start = 0
    n = len(body)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            best = _find_best_break(body, start, end)
            if best > start:
                end = best
        out.append((body[start:end], start, end))
        if end >= n:
            break
        start = max(start + 1, end - chunk_overlap)
    return out


def _find_best_break(text: str, start: int, end: int) -> int:
    """Look for the latest natural separator inside [start, end)."""
    for sep in _SEPARATORS:
        if not sep:
            continue
        cut = text.rfind(sep, start, end)
        if cut > start:
            return cut + len(sep)
    return end
