"""Entity + relation alignment for the per-user knowledge graph.

Without alignment, doc A emits "GWU" and doc B emits "GWU " (trailing space)
or "gwu" as separate MERGE keys, so each doc contributes its own island of
nodes. This module normalizes names and fuzz-matches near-duplicates before
the write hits Neo4j, so the KG converges into one connected graph as docs
accumulate.

Three layers, in order of increasing cost / recall (see #43a in TASKS):
  L1  case + unicode + punctuation normalization (deterministic)
  L2  fuzzy string match against same-type existing entities (rapidfuzz)
  L4  relation predicate canonicalization (small mapping table)

L3 (semantic alignment via bge embeddings for abbreviation-vs-expansion pairs)
is planned separately as #43b.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.graph.schema import GraphEntity, GraphRelationship

# ---------------------------------------------------------------------------
# L1 — name normalization
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?'\"()\[\]]+$")
_LEADING_ARTICLES: tuple[str, ...] = ("the ", "a ", "an ")


def normalize_name(name: str) -> str:
    """Canonical form used as the Neo4j MERGE key for entities.

    Order matters: NFKC first (folds fullwidth/ligatures), then lowercase,
    then strip leading articles and trailing punctuation, then collapse
    internal whitespace. Empty input returns empty string.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).strip().lower()
    for art in _LEADING_ARTICLES:
        if s.startswith(art):
            s = s[len(art) :]
            break
    s = _TRAILING_PUNCT_RE.sub("", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


# ---------------------------------------------------------------------------
# L2 — fuzzy alias detection
# ---------------------------------------------------------------------------

# 0-100 similarity. 90 is safe for named entities: catches typo/spacing
# variants like "Kamalasankaris" vs "Kamalasankari" (1 char off, ~96),
# without collapsing genuinely-different short names like "Java" vs
# "JavaScript" (~67, both Technology). Adjust per per-user tuning later.
FUZZY_THRESHOLD = 90


@dataclass(frozen=True)
class Candidate:
    """A same-type existing entity that a new entity may alias to. Only
    carries the fields alignment needs — display name lives in Neo4j."""

    name_lower: str
    type: str


def find_alias(
    normalized: str,
    entity_type: str,
    candidates: Iterable[Candidate],
) -> str | None:
    """Return the best same-type candidate whose fuzzy similarity clears
    FUZZY_THRESHOLD, or None. Exact matches short-circuit.

    Type-scoping prevents false positives: "Java" and "JavaScript" are both
    Technology at ~67% similarity (would be dropped), but if one were
    Person and the other Technology they'd never be compared. Token-sort
    ratio is order-invariant so "John Smith" vs "Smith, John" aligns.
    """
    if not normalized:
        return None
    best_score = 0.0
    best_match: str | None = None
    for cand in candidates:
        if cand.type != entity_type:
            continue
        if cand.name_lower == normalized:
            return cand.name_lower
        score = fuzz.token_sort_ratio(normalized, cand.name_lower)
        if score > best_score:
            best_score = score
            best_match = cand.name_lower
    if best_score >= FUZZY_THRESHOLD:
        return best_match
    return None


# ---------------------------------------------------------------------------
# L4 — relation predicate normalization
# ---------------------------------------------------------------------------

# Maps common raw predicates to a canonical form. Only forward-direction
# variants are grouped; inverse forms ("authored by" as the inverse of
# "authored") would need source/target swapping which is out of scope for
# L4 — those still create their own edges. Additions welcome as the corpus
# surfaces more variants.
RELATION_ALIASES: dict[str, str] = {
    # authorship (creator → work)
    "author of": "authored",
    "authors": "authored",
    "wrote": "authored",
    "writes": "authored",
    "co-authored": "co-authored",
    "coauthored": "co-authored",
    "co-author of": "co-authored",
    # affiliation (person → org)
    "works at": "affiliated with",
    "works for": "affiliated with",
    "employed by": "affiliated with",
    "employee of": "affiliated with",
    "member of": "affiliated with",
    # location (entity → location)
    "based in": "located in",
    "headquartered in": "located in",
    "situated in": "located in",
    # usage (user → tool)
    "using": "uses",
    "utilizes": "uses",
    "utilises": "uses",
    "leverages": "uses",
    # dependency
    "requires": "depends on",
    "relies on": "depends on",
    "built on": "based on",
    # comparison (source outperforms target)
    "better than": "outperforms",
    "exceeds": "outperforms",
    "surpasses": "outperforms",
    # composition
    "consists of": "contains",
    "comprised of": "contains",
    "includes": "contains",
}


def normalize_relation(relation: str) -> str:
    """Map a raw relation phrase to its canonical form. Unknown phrases are
    lowercased+trimmed and passed through unchanged — better a slightly
    noisy predicate than a lossy remap."""
    if not relation:
        return ""
    key = _WHITESPACE_RE.sub(" ", relation.strip().lower())
    key = _TRAILING_PUNCT_RE.sub("", key)
    return RELATION_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Batch aligner — the entrypoint called by the worker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlignedEntity:
    """An entity resolved to canonical form and ready for upsert."""

    name: str  # display form (raw name from extraction; Neo4j preserves first-write)
    name_lower: str  # MERGE key (normalized or aliased-to)
    type: str
    description: str


@dataclass(frozen=True)
class AlignedRelationship:
    """A relationship with source/target rewritten to canonical name_lower
    keys and predicate mapped through RELATION_ALIASES."""

    source_lower: str
    target_lower: str
    relation: str


def align_batch(
    entities: list[GraphEntity],
    relationships: list[GraphRelationship],
    existing_candidates: list[Candidate],
) -> tuple[list[AlignedEntity], list[AlignedRelationship]]:
    """Align one doc's extraction against the existing user KG.

    Steps:
    1. Normalize each incoming entity's name.
    2. Fuzzy-match against the existing candidates AND against entities
       already aligned earlier in this same batch — so a doc that mentions
       both "GWU" and "George Washington University" (rare but possible)
       collapses to one node when they cross the threshold.
    3. Build a lookup: raw extraction name → canonical name_lower.
    4. Rewrite relationships through that lookup; normalize their
       predicates; drop self-loops and endpoint-missing edges.
    """
    aligned_entities: list[AlignedEntity] = []
    # Rolling map from the raw extraction string (lowercased) to the
    # canonical name_lower it aligned to. Populated as we walk entities.
    raw_to_canonical: dict[str, str] = {}
    # Grows as we align each entity so later ones in this batch can alias
    # to earlier ones.
    live_candidates: list[Candidate] = list(existing_candidates)
    seen_canonical: set[str] = set()

    for e in entities:
        raw = (e.name or "").strip()
        if not raw:
            continue
        normalized = normalize_name(e.name)
        if not normalized:
            continue
        raw_lower = raw.lower()

        alias = find_alias(normalized, e.type, live_candidates)
        canonical_lower = alias or normalized
        raw_to_canonical[raw_lower] = canonical_lower

        if canonical_lower in seen_canonical:
            # Already emitted (either same normalized form or a fuzzy
            # match to an already-aligned entity in this batch). Don't
            # emit a second AlignedEntity for it — Neo4j MERGE would
            # dedupe anyway, but this keeps the log counts honest.
            continue
        seen_canonical.add(canonical_lower)
        aligned_entities.append(
            AlignedEntity(
                name=raw,
                name_lower=canonical_lower,
                type=e.type,
                description=e.description,
            )
        )
        live_candidates.append(Candidate(name_lower=canonical_lower, type=e.type))

    aligned_rels: list[AlignedRelationship] = []
    seen_rels: set[tuple[str, str, str]] = set()
    for r in relationships:
        src_raw = (r.source or "").strip().lower()
        tgt_raw = (r.target or "").strip().lower()
        src_canonical = raw_to_canonical.get(src_raw)
        tgt_canonical = raw_to_canonical.get(tgt_raw)
        if not src_canonical or not tgt_canonical:
            continue
        if src_canonical == tgt_canonical:
            continue
        rel_canonical = normalize_relation(r.relation)
        if not rel_canonical:
            continue
        key3 = (src_canonical, tgt_canonical, rel_canonical)
        if key3 in seen_rels:
            continue
        seen_rels.add(key3)
        aligned_rels.append(
            AlignedRelationship(
                source_lower=src_canonical,
                target_lower=tgt_canonical,
                relation=rel_canonical,
            )
        )
    return aligned_entities, aligned_rels
