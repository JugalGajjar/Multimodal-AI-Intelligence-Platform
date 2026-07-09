"""L3 semantic entity alignment via bge-small-en-v1.5 embeddings.

Catches abbreviation/expansion pairs that L1 (normalization) and L2 (fuzzy
string) miss:

    SFT ↔ Supervised Fine-Tuning     (fuzz score ~10, way below L2 threshold)
    GWU ↔ George Washington University
    RSAT ↔ RSAT Model
    Explainable AI (XAI) ↔ explainable AI

Approach: on ingest, embed each entity's `name: description` through the same
bge model retrieval uses, then cosine-similarity against existing same-type
entities' stored embeddings. If similarity clears the threshold, alias to the
existing entity (its Neo4j node stays as-is; the incoming entity merges in via
its canonical name_lower). Downstream relationship endpoints get rewritten
through the alias map.

Embeddings live on the :Entity Neo4j node (property `embedding: list[float]`),
set only ON CREATE so an aliased write doesn't overwrite the existing
authoritative embedding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticCandidate:
    """An existing entity fetched from Neo4j that a new entity may semantically
    alias to. Immutable so it can go into sets / used as dict keys downstream."""

    name_lower: str
    type: str
    # bge-small-en-v1.5 outputs are L2-normalized 384-dim vectors, so cosine
    # similarity == dot product. Storing as a tuple keeps the dataclass hashable.
    embedding: tuple[float, ...]


def format_entity_text(name: str, description: str | None = None) -> str:
    """The string handed to the embedding model.

    Description adds a strong semantic anchor when present ('SFT' alone is
    ambiguous; 'SFT: supervised fine-tuning method' is not). For entities
    without a description we fall back to just the name — sub-optimal but the
    caller may still get useful similarity on longer canonical names.
    """
    name = (name or "").strip()
    desc = (description or "").strip()
    if desc:
        return f"{name}: {desc}"
    return name


def _dot(a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
    """Dot product of two equal-length vectors. bge outputs are L2-normalized,
    so this equals cosine similarity — no re-normalization needed."""
    # Keeping this hand-rolled rather than pulling numpy in for a hot path
    # that runs on modest-sized entity lists. For a 384-dim × 500-entity
    # pool this loops ~200k floats — well under 1ms in CPython.
    total = 0.0
    for x, y in zip(a, b, strict=True):
        total += x * y
    return total


def find_semantic_alias(
    embedding: list[float] | tuple[float, ...],
    entity_type: str,
    candidates: Iterable[SemanticCandidate],
    same_type_threshold: float,
    cross_type_threshold: float,
) -> str | None:
    """Return the name_lower of the best candidate whose cosine similarity
    to *embedding* clears the appropriate threshold, else None.

    Two-tier (#43d): same-type matches use `same_type_threshold` (looser);
    cross-type matches use `cross_type_threshold` (stricter). Cross-type is
    allowed because the extractor is inconsistent about typing (SFT gets
    Technology, Supervised Fine-Tuning gets Concept — same real concept),
    but the higher bar prevents genuine cross-type collisions like Java the
    Location vs Java the Technology at cosine ~0.6.

    Same-type wins ties: if a same-type candidate and a cross-type candidate
    both clear their respective thresholds, the same-type one is returned
    (it's the safer merge). Within a type-class, best score wins.
    """
    if not embedding:
        return None

    best_same_score = 0.0
    best_same_match: str | None = None
    best_cross_score = 0.0
    best_cross_match: str | None = None

    for cand in candidates:
        if not cand.embedding:
            continue
        try:
            score = _dot(embedding, cand.embedding)
        except ValueError:
            # Dimension mismatch (e.g. an old row with a partial vector) —
            # skip rather than crash the whole batch.
            continue
        if cand.type == entity_type:
            if score > best_same_score:
                best_same_score = score
                best_same_match = cand.name_lower
        else:
            if score > best_cross_score:
                best_cross_score = score
                best_cross_match = cand.name_lower

    if best_same_score >= same_type_threshold:
        return best_same_match
    if best_cross_score >= cross_type_threshold:
        return best_cross_match
    return None
