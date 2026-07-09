"""LLM-driven entity & relationship extraction.

Two paths, feature-flagged by `settings.graph_extraction_map_reduce`:

- **Map-reduce (default, #43)**: per-chunk two-pass extraction — Pass 1 emits
  entities from a single chunk, Pass 2 emits relations given that chunk's
  entity list. Chunks run concurrently under a semaphore whose size matches
  the Groq key pool (each in-flight call naturally lands on its own key).
  Failures are per-chunk isolated: one 429 doesn't sink the whole doc.

- **Single-shot (legacy)**: send the whole (truncated) doc in one call.
  Preserved for feature-flag rollback; delete when the flag comes out.

Retry rules for the legacy path:
  429 with hint ≤ 30s  → sleep + retry (per-minute cap), up to MAX_RETRIES.
  429 with hint > 30s  → bail (daily cap; worker shouldn't block).
  400 json_validate    → retry once (model is non-deterministic).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from app.core.config import settings
from app.graph.schema import ExtractionResult, GraphEntity, GraphRelationship
from app.rag.groq_chat import GroqChatError, chat_completion


@dataclass(frozen=True)
class ExtractionOutcome:
    """Outcome of a `safe_extract_entities` call. `transient_failure=True`
    means the model never produced a valid result (429/400/network) and a
    retry from the caller is likely to succeed; `transient_failure=False`
    with an empty result means the model genuinely found no entities."""

    result: ExtractionResult
    transient_failure: bool


log = logging.getLogger("mmap.graph.extraction")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# Pass 1 — entities only. Domain-neutral. Explicitly skips Date entities
# (general modeling principle: dates describing when something happened
# are attributes of the connected entity, not entities themselves).
SYSTEM_PROMPT_ENTITIES = (
    "You are an information extraction system. Read the passage and produce a "
    "JSON object listing the named entities mentioned. Works across any domain "
    "— medical, legal, business, scientific, technical.\n\n"
    "STRICT JSON schema (type is exactly one of the seven allowed values):\n"
    "{\n"
    '  "entities": [\n'
    '    {"name": "canonical noun phrase", "type": "Person", '
    '"description": "2-6 word tag"}\n'
    "  ]\n"
    "}\n"
    "Allowed entity types: Person, Organization, Location, Concept, "
    "Technology, Product, Event.\n\n"
    "Rules:\n"
    '- Names must be canonical (no pronouns, drop articles like "the").\n'
    "- If unsure of entity type, use Concept.\n"
    "- Prefer named, specific entities; skip generic words.\n"
    "- Descriptions MUST be a 2-6 word tag (role, category, or one-liner) "
    "— never a full sentence. Long descriptions waste output tokens.\n"
    "- Do NOT create a Date entity. Timestamps that describe when something "
    "happened (a job start date, a publication month, a conference year) "
    "belong as attributes of the connected entity, not as entities in "
    "their own right. Omit them.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    '- Return {"entities": []} only when the passage has no named entities at all.'
)

# Pass 2 — relations given entity list. Domain-neutral. Cannot invent new
# entity names (source/target must appear in the provided list). One
# domain-neutral few-shot example demonstrating apposition, comparison,
# and possessive prose patterns.
SYSTEM_PROMPT_RELATIONS = (
    "You are an information extraction system. Given a text passage and a list "
    "of entities already extracted from it, produce a JSON object listing "
    "every relation the passage supports between those listed entities. Works "
    "across any domain.\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "relationships": [\n'
    '    {"source": "entity name", "target": "entity name", '
    '"relation": "short verb phrase"}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- source and target MUST both be names that appear in the provided entity "
    "list. Do not invent new entity names.\n"
    "- You MUST extract every relation the passage implies, including relations "
    "expressed through:\n"
    '  * apposition or parentheses ("Jane Smith (MIT)" → Smith affiliated with MIT)\n'
    "  * juxtaposition on the same line (title-slide bylines, author lists,\n"
    "    tables where a row groups related entities)\n"
    '  * comparison and result verbs ("outperforms", "reduces", "increases", "cites")\n'
    '  * possessive or attributive prose ("Anthropic\'s Claude", "the FDA-approved drug")\n'
    "- Slide, OCR, and bullet-list text is often compact — infer the relation "
    "from proximity when the surrounding text makes it unambiguous.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    '- Return {"relationships": []} only when the passage supports NO relations '
    "between the listed entities.\n\n"
    "Example (illustrates apposition + comparison + implicit relations — the "
    "domain is illustrative, apply the same reasoning to whatever passage "
    "you receive):\n"
    'TEXT: "Jane Smith (MIT) proposes TinyGraph — a variant that outperforms '
    'GraphBERT on the WebQA benchmark."\n'
    'ENTITIES: [{"name":"Jane Smith","type":"Person"},{"name":"MIT",'
    '"type":"Organization"},{"name":"TinyGraph","type":"Technology"},'
    '{"name":"GraphBERT","type":"Technology"},{"name":"WebQA","type":"Concept"}]\n'
    "OUTPUT:\n"
    "{\n"
    '  "relationships": [\n'
    '    {"source": "Jane Smith", "target": "MIT", "relation": "affiliated with"},\n'
    '    {"source": "Jane Smith", "target": "TinyGraph", "relation": "proposes"},\n'
    '    {"source": "TinyGraph", "target": "GraphBERT", "relation": "outperforms"},\n'
    '    {"source": "TinyGraph", "target": "WebQA", "relation": "evaluated on"}\n'
    "  ]\n"
    "}"
)


# Legacy single-shot prompt — kept as a self-contained string behind the
# feature flag so `GRAPH_EXTRACTION_MAP_REDUCE=false` reverts to the pre-#43
# behavior exactly. Delete when the flag comes out.
SYSTEM_PROMPT = (
    "You are an information extraction system. Read the passage and produce a "
    "JSON object describing the entities mentioned and how they relate. Works "
    "across any domain — medical, legal, business, scientific, technical.\n\n"
    "STRICT JSON schema (types are exactly one of the eight allowed values):\n"
    "{\n"
    '  "entities": [\n'
    '    {"name": "canonical noun phrase", "type": "Person", '
    '"description": "2-6 word tag"}\n'
    "  ],\n"
    '  "relationships": [\n'
    '    {"source": "entity name", "target": "entity name", '
    '"relation": "short verb phrase"}\n'
    "  ]\n"
    "}\n"
    "Allowed entity types: Person, Organization, Location, Concept, "
    "Technology, Product, Event, Date.\n\n"
    "Rules:\n"
    '- Names must be canonical (no pronouns, drop articles like "the").\n'
    "- Each relationship source and target MUST appear in entities.\n"
    "- If unsure of entity type, use Concept.\n"
    "- Prefer named, specific entities; skip generic words.\n"
    "- Descriptions MUST be a 2-6 word tag (role, category, or one-liner) "
    "— never a full sentence. Long descriptions waste output tokens that "
    "would otherwise go to relationships.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    "- Only return empty lists when the passage contains no named entities "
    "at all. If entities are present, you MUST extract every relation the "
    "passage implies, including relations expressed through:\n"
    '  * apposition or parentheses ("Jane Smith (MIT)" → Smith affiliated with MIT)\n'
    "  * juxtaposition on the same line/slide (title-slide bylines, author lists,\n"
    "    tables where a row groups related entities)\n"
    '  * comparison and result verbs ("outperforms", "reduces", "increases", "cites")\n'
    '  * possessive or attributive prose ("Anthropic\'s Claude", "the FDA-approved drug")\n'
    "- Slide, OCR, and bullet-list text is often compact — infer the relation "
    "from proximity when the surrounding text makes it unambiguous.\n\n"
    "Example (illustrates typing + explicit + implicit relations — the domain "
    "is illustrative, apply the same reasoning to whatever passage you receive):\n"
    'Input: "Jane Smith (MIT) proposes TinyGraph — a variant that outperforms '
    'GraphBERT on the WebQA benchmark."\n'
    "Output:\n"
    "{\n"
    '  "entities": [\n'
    '    {"name": "Jane Smith", "type": "Person", "description": "researcher"},\n'
    '    {"name": "MIT", "type": "Organization", "description": "research institution"},\n'
    '    {"name": "TinyGraph", "type": "Technology", "description": "lightweight graph model"},\n'
    '    {"name": "GraphBERT", "type": "Technology", "description": "baseline graph model"},\n'
    '    {"name": "WebQA", "type": "Concept", "description": "QA benchmark"}\n'
    "  ],\n"
    '  "relationships": [\n'
    '    {"source": "Jane Smith", "target": "MIT", "relation": "affiliated with"},\n'
    '    {"source": "Jane Smith", "target": "TinyGraph", "relation": "proposes"},\n'
    '    {"source": "TinyGraph", "target": "GraphBERT", "relation": "outperforms"},\n'
    '    {"source": "TinyGraph", "target": "WebQA", "relation": "evaluated on"}\n'
    "  ]\n"
    "}"
)

# Legacy path caps input length to fit the pre-#43 single call. Not used
# on the map-reduce path (chunks are already bounded by chunker).
MAX_INPUT_CHARS = 12_000
MAX_RETRIES = 3
RETRY_BACKOFF_CAP_SECONDS = 30.0
RETRY_GIVE_UP_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Groq retry-hint parsing (legacy path only)
# ---------------------------------------------------------------------------


_RETRY_AFTER_PATTERNS = (
    re.compile(r"try again in (\d+)m([\d.]+)s", re.IGNORECASE),
    re.compile(r"try again in ([\d.]+)s", re.IGNORECASE),
    re.compile(r"try again in ([\d.]+)ms", re.IGNORECASE),
)


def _parse_retry_after(body: object) -> float | None:
    msg = _error_message(body)
    if not msg:
        return None
    for pat in _RETRY_AFTER_PATTERNS:
        m = pat.search(msg)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2:
            return float(groups[0]) * 60 + float(groups[1])
        value = float(groups[0])
        if "ms" in pat.pattern:
            return value / 1000.0
        return value
    return None


def _error_message(body: object) -> str:
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        err = body.get("error") if "error" in body else None
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(body.get("detail"), str):
            return body["detail"]
    return str(body)


def _is_json_validate_failure(exc: GroqChatError) -> bool:
    if exc.status_code != 400:
        return False
    msg = _error_message(exc.body).lower()
    return "validate json" in msg or "json_validate_failed" in msg


# ---------------------------------------------------------------------------
# JSON recovery
# ---------------------------------------------------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(raw: str) -> str | None:
    if not raw:
        return None
    fenced = _JSON_FENCE_RE.search(raw)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return None


def _load_json(raw: str) -> dict | None:
    """Robust JSON load: tolerates markdown fences and prose preamble."""
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is None:
            return None
        try:
            obj = json.loads(recovered)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# Map-reduce: per-chunk two-pass extraction
# ---------------------------------------------------------------------------


PASS_MAX_TOKENS = 2048  # both passes emit modest JSON; 2048 leaves headroom
# for CoT under reasoning_effort="medium" while staying
# well under Groq's 8K TPM per-request ceiling.


async def _call_pass1(chunk_text: str) -> str:
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_ENTITIES},
            {"role": "user", "content": chunk_text},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        max_tokens=PASS_MAX_TOKENS,
        reasoning_effort="medium",
        response_format={"type": "json_object"},
    )


async def _call_pass2(chunk_text: str, entities: list[GraphEntity]) -> str:
    entity_list = [{"name": e.name, "type": e.type} for e in entities]
    user_msg = f"TEXT:\n{chunk_text}\n\nENTITIES:\n{json.dumps(entity_list, ensure_ascii=False)}"
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_RELATIONS},
            {"role": "user", "content": user_msg},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        max_tokens=PASS_MAX_TOKENS,
        reasoning_effort="medium",
        response_format={"type": "json_object"},
    )


def _parse_entities(raw: str) -> list[GraphEntity]:
    data = _load_json(raw)
    if data is None:
        log.warning("pass1 returned non-JSON: %r", raw[:200])
        return []
    items = data.get("entities")
    if not isinstance(items, list):
        return []
    out: list[GraphEntity] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            out.append(GraphEntity.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out


def _parse_relations(raw: str, entities: list[GraphEntity]) -> list[GraphRelationship]:
    data = _load_json(raw)
    if data is None:
        log.warning("pass2 returned non-JSON: %r", raw[:200])
        return []
    items = data.get("relationships")
    if not isinstance(items, list):
        return []
    # Case-insensitive name membership check — pass 2 model may return
    # slightly-different casing than pass 1 emitted.
    valid_names = {e.name.strip().lower() for e in entities if e.name}
    out: list[GraphRelationship] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            rel = GraphRelationship.model_validate(item)
        except Exception:  # noqa: BLE001
            continue
        # Pass 2 was told the source/target must come from the provided
        # entity list — enforce it, drop fabrications.
        if rel.source.strip().lower() not in valid_names:
            continue
        if rel.target.strip().lower() not in valid_names:
            continue
        out.append(rel)
    return out


async def _process_chunk(
    chunk_text: str, semaphore: asyncio.Semaphore
) -> tuple[ExtractionResult, bool]:
    """Run Pass 1 + Pass 2 on one chunk. Returns (result, transient_failure).

    transient_failure=True means the LLM call raised — a caller-level retry
    might succeed. transient_failure=False with an empty result means the
    chunk genuinely had no entities.

    Semaphore is held ONLY during the LLM call (scope B): the second pass
    releases it and reacquires so other chunks' passes can interleave.
    """
    try:
        async with semaphore:
            pass1_raw = await _call_pass1(chunk_text)
    except GroqChatError as exc:
        log.warning("chunk pass1 upstream failure (%s): %s", exc.status_code, exc.body)
        return ExtractionResult(entities=[], relationships=[]), True
    except Exception as exc:  # noqa: BLE001
        log.warning("chunk pass1 unexpected failure: %s", exc)
        return ExtractionResult(entities=[], relationships=[]), True

    entities = _parse_entities(pass1_raw)
    if not entities:
        # Genuinely empty chunk (or the parser rejected everything). Skip
        # pass 2 — no need to burn a call asking about no entities.
        return ExtractionResult(entities=[], relationships=[]), False

    try:
        async with semaphore:
            pass2_raw = await _call_pass2(chunk_text, entities)
    except GroqChatError as exc:
        log.warning("chunk pass2 upstream failure (%s): %s", exc.status_code, exc.body)
        # Pass 1 entities still land — better half than nothing.
        return ExtractionResult(entities=entities, relationships=[]), False
    except Exception as exc:  # noqa: BLE001
        log.warning("chunk pass2 unexpected failure: %s", exc)
        return ExtractionResult(entities=entities, relationships=[]), False

    relations = _parse_relations(pass2_raw, entities)
    return ExtractionResult(entities=entities, relationships=relations), False


def _merge_results(results: list[ExtractionResult]) -> ExtractionResult:
    """Union entities and relations across chunks.

    Downstream alignment (`app.graph.alignment.align_batch`) does the real
    dedup work (normalize_name + fuzzy alias + relation predicate mapping),
    so this merge is intentionally cheap: concatenate, drop empties. The
    alignment pass handles cross-chunk canonicalization.
    """
    entities: list[GraphEntity] = []
    relationships: list[GraphRelationship] = []
    for r in results:
        if r is None:
            continue
        entities.extend(r.entities)
        relationships.extend(r.relationships)
    return ExtractionResult(entities=entities, relationships=relationships)


# ---------------------------------------------------------------------------
# Phase 3 — cross-chunk relation reconciliation (#43b)
# ---------------------------------------------------------------------------

# Pair reconciliation prompt. Short output (one predicate + direction or null)
# so max_tokens can stay tight — many small calls beat few large ones under
# Groq's TPM ceiling.
SYSTEM_PROMPT_RECONCILE = (
    "You are checking whether a text unambiguously supports a factual relation "
    "between two named entities. You will be given two entities and text "
    "snippets from a single document that mention them. Works across any "
    "domain — medical, legal, business, scientific, technical.\n\n"
    "STRICT JSON schema:\n"
    "{\n"
    '  "relation": "short verb phrase or null",\n'
    '  "direction": "AB or BA"\n'
    "}\n\n"
    "Rules:\n"
    "- Only assert a relation the text clearly supports. If uncertain, return "
    '{"relation": null}.\n'
    "- Do NOT invent relations from common knowledge or plausible inference — "
    "only from what the snippets actually say.\n"
    "- When the two entities co-appear in the SAME snippet (co-mentioned on "
    "one line, in a byline, in an author list, in an apposition, or in an "
    "entity list), a relation is more likely than when they appear in "
    "different snippets. Infer the relation from the co-mention pattern "
    "even when it's not spelled out with an explicit verb. Examples: two "
    "names on a title-slide byline → 'co-authored with'; a person's name "
    "followed by an institution in parentheses → 'affiliated with'; two "
    "items joined by 'and' in a bulleted attribute → the shared attribute.\n"
    "- Relation verb phrase must be short (1-4 words): e.g. 'authored', "
    "'affiliated with', 'outperforms', 'located in', 'treats', 'cites'.\n"
    "- Direction picks the natural reading of the text: 'AB' means A → B "
    "('Alice authored Book' → AB); 'BA' means B → A ('Book authored by Alice' "
    "→ BA). Choose whichever the snippets support.\n"
    "- Output JSON ONLY (no markdown fences, no commentary).\n"
    '- If no relation is supported, return {"relation": null}.'
)


RECONCILE_MAX_SNIPPETS = 3
RECONCILE_SNIPPET_CHARS = 500
RECONCILE_MAX_TOKENS = 512  # output is tiny — cap keeps TPM footprint low


def _cooccurrence_score(chunks_a: frozenset[int], chunks_b: frozenset[int]) -> int:
    """Higher score = pair is more likely to be genuinely related.

    Same chunk (+3): Pass 2 for that chunk already had a shot but sometimes
      misses — still worth a targeted check. Adjacent (+2) and nearby-≤3
      (+1) approximate section-level proximity in section-aware chunking.
    """
    score = 0
    for a in chunks_a:
        for b in chunks_b:
            gap = abs(a - b)
            if gap == 0:
                score += 3
            elif gap == 1:
                score += 2
            elif gap <= 3:
                score += 1
    return score


def _gather_snippets(
    chunks: list[str],
    indices: frozenset[int],
    max_snippets: int,
    max_chars: int,
) -> str:
    """Concatenate up to *max_snippets* chunk texts, each truncated to
    *max_chars*, separated by a visual break so the model can see boundaries."""
    picked = sorted(indices)[:max_snippets]
    parts: list[str] = []
    for i in picked:
        if 0 <= i < len(chunks):
            snippet = (chunks[i] or "").strip()[:max_chars]
            if snippet:
                parts.append(snippet)
    return "\n\n---\n\n".join(parts)


async def _reconcile_pair(
    *,
    name_a: str,
    name_b: str,
    type_a: str,
    type_b: str,
    snippet_a: str,
    snippet_b: str,
    semaphore: asyncio.Semaphore,
) -> GraphRelationship | None:
    """One LLM call to decide if a doc supports a relation between A and B.

    Returns a GraphRelationship (source/target set per returned direction)
    or None when the model declines / errors / bad JSON.
    """
    user_msg = (
        f"Entity A: name={name_a!r}, type={type_a!r}\n"
        f"Entity B: name={name_b!r}, type={type_b!r}\n\n"
        f"Snippets from the document mentioning A:\n{snippet_a}\n\n"
        f"Snippets from the document mentioning B:\n{snippet_b}"
    )
    try:
        async with semaphore:
            raw = await chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_RECONCILE},
                    {"role": "user", "content": user_msg},
                ],
                model=settings.groq_extraction_model,
                temperature=0.0,
                # Low reasoning: this is a binary+labeling task, not deep
                # inference. Keeps per-call TPM footprint minimal so we can
                # fit many pair checks under the Groq ceiling.
                max_tokens=RECONCILE_MAX_TOKENS,
                reasoning_effort="low",
                response_format={"type": "json_object"},
            )
    except GroqChatError as exc:
        log.info("reconcile pair upstream failure (%s)", exc.status_code)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("reconcile pair unexpected: %s", exc)
        return None

    data = _load_json(raw)
    if data is None:
        return None
    relation = data.get("relation")
    if relation is None or not isinstance(relation, str) or not relation.strip():
        return None
    predicate = relation.strip()
    direction = str(data.get("direction") or "AB").strip().upper()

    src, tgt = (name_a, name_b) if direction != "BA" else (name_b, name_a)
    try:
        return GraphRelationship(source=src, target=tgt, relation=predicate)
    except Exception:  # noqa: BLE001
        return None


async def _reconcile_relations(
    *,
    chunks: list[str],
    chunk_entities: dict[int, list[GraphEntity]],
    existing: ExtractionResult,
    semaphore: asyncio.Semaphore,
    top_k: int,
) -> list[GraphRelationship]:
    """Cross-chunk relation reconciliation. See #43b.

    For each candidate pair (A, B) of extracted entities, gather text
    snippets from chunks where each appears, and ask the LLM whether the
    document supports a relation between them. Bounded by *top_k* candidates
    scored by co-occurrence proximity across chunks.

    Returns any new relations the model asserts — merged into the extraction
    result by the caller. Alignment (see `app.graph.alignment.align_batch`)
    deduplicates and canonicalizes downstream.
    """
    if not chunk_entities or top_k <= 0:
        return []

    # entity_key (name_lower) → chunk indices it appeared in, plus display/type
    e_to_chunks: dict[str, set[int]] = defaultdict(set)
    e_type: dict[str, str] = {}
    e_display: dict[str, str] = {}
    for chunk_idx, ents in chunk_entities.items():
        for e in ents:
            key = (e.name or "").strip().lower()
            if not key:
                continue
            e_to_chunks[key].add(chunk_idx)
            e_type.setdefault(key, e.type)
            e_display.setdefault(key, e.name)

    if len(e_to_chunks) < 2:
        return []

    # Existing relation pairs — both directions, so we don't re-ask about
    # any (A, B) or (B, A) already emitted by Pass 2.
    existing_pairs: set[frozenset[str]] = set()
    for r in existing.relationships:
        a = (r.source or "").strip().lower()
        b = (r.target or "").strip().lower()
        if a and b and a != b:
            existing_pairs.add(frozenset((a, b)))

    # Score all unrelated pairs, keep top_k.
    keys = sorted(e_to_chunks.keys())
    scored: list[tuple[int, str, str]] = []
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1 :]:
            if frozenset((key_a, key_b)) in existing_pairs:
                continue
            if e_type.get(key_a) != e_type.get(key_b):
                pass  # cross-type pairs are valid (Person↔Org etc.); no filter
            score = _cooccurrence_score(
                frozenset(e_to_chunks[key_a]),
                frozenset(e_to_chunks[key_b]),
            )
            if score > 0:
                scored.append((score, key_a, key_b))

    if not scored:
        log.info("reconcile: no candidate pairs")
        return []

    scored.sort(key=lambda t: -t[0])
    top = scored[:top_k]

    async def _one(pair: tuple[int, str, str]) -> GraphRelationship | None:
        _score, ka, kb = pair
        return await _reconcile_pair(
            name_a=e_display[ka],
            name_b=e_display[kb],
            type_a=e_type[ka],
            type_b=e_type[kb],
            snippet_a=_gather_snippets(
                chunks,
                frozenset(e_to_chunks[ka]),
                RECONCILE_MAX_SNIPPETS,
                RECONCILE_SNIPPET_CHARS,
            ),
            snippet_b=_gather_snippets(
                chunks,
                frozenset(e_to_chunks[kb]),
                RECONCILE_MAX_SNIPPETS,
                RECONCILE_SNIPPET_CHARS,
            ),
            semaphore=semaphore,
        )

    results = await asyncio.gather(*[_one(p) for p in top])
    new_rels = [r for r in results if r is not None]
    log.info(
        "reconcile: candidates=%d checked=%d new_rels=%d",
        len(scored),
        len(top),
        len(new_rels),
    )
    return new_rels


def _default_concurrency() -> int:
    """Match Groq key pool size so each in-flight call naturally lands on
    its own key (no TPM contention within a key's budget). Falls back to
    3 when the pool is a single key — modest concurrency without failure
    storms."""
    pool_size = len(settings.groq_key_pool)
    return max(1, pool_size) if pool_size > 1 else 3


async def extract_entities_from_chunks(
    chunks: list[str],
    *,
    concurrency: int | None = None,
) -> ExtractionResult:
    """Map-reduce entity extraction over a list of chunk texts.

    Concurrency defaults to the Groq key pool size so each concurrent LLM
    call naturally lands on a different key. Failures are per-chunk isolated:
    one chunk 429ing doesn't cancel the others. Returns the concatenated
    ExtractionResult across all successful chunks — downstream `align_batch`
    handles cross-chunk canonicalization.

    When `graph_extraction_reconcile` is on, a Phase 3 cross-chunk
    reconciliation pass runs after merge and adds relations Pass 2 missed
    (entities that appear in different chunks and never met each other in
    a single chunk's Pass 2 prompt).
    """
    non_empty = [c for c in chunks if c and c.strip()]
    if not non_empty:
        return ExtractionResult(entities=[], relationships=[])

    n = concurrency if concurrency is not None else _default_concurrency()
    semaphore = asyncio.Semaphore(max(1, n))

    tasks = [_process_chunk(c, semaphore) for c in non_empty]
    per_chunk = await asyncio.gather(*tasks)

    ok_count = sum(1 for _, transient in per_chunk if not transient)
    results = [r for r, _ in per_chunk]

    # Track per-chunk entities for reconciliation candidate scoring — index
    # matches `non_empty` since map order is preserved by asyncio.gather.
    chunk_entities: dict[int, list[GraphEntity]] = {
        i: list(r.entities) for i, r in enumerate(results)
    }

    merged = _merge_results(results)
    log.info(
        "extract: chunks=%d/%d ok, ents=%d rels=%d",
        ok_count,
        len(non_empty),
        len(merged.entities),
        len(merged.relationships),
    )

    if settings.graph_extraction_reconcile:
        new_rels = await _reconcile_relations(
            chunks=non_empty,
            chunk_entities=chunk_entities,
            existing=merged,
            semaphore=semaphore,
            top_k=settings.graph_extraction_reconcile_top_k,
        )
        if new_rels:
            merged = ExtractionResult(
                entities=merged.entities,
                relationships=merged.relationships + new_rels,
            )

    return merged


# ---------------------------------------------------------------------------
# Legacy single-shot path (behind feature flag)
# ---------------------------------------------------------------------------


async def _call_llm(text: str) -> str:
    return await chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        model=settings.groq_extraction_model,
        temperature=0.0,
        # Same #42a/#42b tuning as the pre-map-reduce single-shot behavior:
        # reasoning_effort="medium" + max_tokens=5120 fits under Groq's 8K
        # TPM per-request ceiling on free tier.
        max_tokens=5120,
        reasoning_effort="medium",
        response_format={"type": "json_object"},
    )


def _parse_response(raw: str) -> ExtractionResult:
    data = _load_json(raw)
    if data is None:
        log.warning("entity extraction returned non-JSON: %r", raw[:200])
        return ExtractionResult(entities=[], relationships=[])
    try:
        result = ExtractionResult.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction validation failed (%s); data=%r", exc, data)
        return ExtractionResult(entities=[], relationships=[])
    return result.normalize()


async def _extract_entities_single_shot(text: str) -> ExtractionResult:
    truncated = text[:MAX_INPUT_CHARS]
    json_retry_used = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = await _call_llm(truncated)
            return _parse_response(raw)
        except GroqChatError as exc:
            if exc.status_code == 429:
                wait = _parse_retry_after(exc.body)
                if wait is not None and wait <= RETRY_GIVE_UP_SECONDS and attempt < MAX_RETRIES:
                    sleep_for = min(wait + 0.5, RETRY_BACKOFF_CAP_SECONDS)
                    log.info(
                        "extraction 429: per-minute cap, sleeping %.1fs (attempt %d/%d)",
                        sleep_for,
                        attempt,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(sleep_for)
                    continue
                raise
            if _is_json_validate_failure(exc) and not json_retry_used:
                json_retry_used = True
                log.info("extraction 400 json_validate_failed — retrying once")
                continue
            raise

    raise GroqChatError(429, {"detail": f"extraction exhausted {MAX_RETRIES} retries"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_entities(text: str) -> ExtractionResult:
    """Legacy text-in entry point. Kept for callers that still pass raw
    OCR text; internally routes through the map-reduce path (as a single
    chunk) when the feature flag is on, else the pre-#43 single-shot path.
    Prefer `extract_entities_from_chunks()` when you already have chunks."""
    if not text or not text.strip():
        return ExtractionResult(entities=[], relationships=[])
    if settings.graph_extraction_map_reduce:
        return await extract_entities_from_chunks([text])
    return await _extract_entities_single_shot(text)


async def safe_extract_entities(chunks: list[str]) -> ExtractionOutcome:
    """Never raises. Returns an outcome flagging whether the empty case was
    due to a transient upstream issue (retry likely helps) or a real empty
    extraction. Accepts a list of chunk texts; wrap a legacy text-only call
    as `safe_extract_entities([text])`."""
    try:
        non_empty = [c for c in chunks if c and c.strip()]
        if not non_empty:
            return ExtractionOutcome(
                result=ExtractionResult(entities=[], relationships=[]),
                transient_failure=False,
            )

        if settings.graph_extraction_map_reduce:
            n = _default_concurrency()
            semaphore = asyncio.Semaphore(max(1, n))
            per_chunk = await asyncio.gather(*(_process_chunk(c, semaphore) for c in non_empty))
            results = [r for r, _ in per_chunk]
            transient_flags = [t for _, t in per_chunk]
            ok_count = sum(1 for t in transient_flags if not t)

            chunk_entities: dict[int, list[GraphEntity]] = {
                i: list(r.entities) for i, r in enumerate(results)
            }
            merged = _merge_results(results)
            log.info(
                "extract: chunks=%d/%d ok, ents=%d rels=%d",
                ok_count,
                len(non_empty),
                len(merged.entities),
                len(merged.relationships),
            )

            # Reconciliation (#43b) — cross-chunk relations Pass 2 missed
            # because it only saw its own chunk's entity list.
            if settings.graph_extraction_reconcile:
                new_rels = await _reconcile_relations(
                    chunks=non_empty,
                    chunk_entities=chunk_entities,
                    existing=merged,
                    semaphore=semaphore,
                    top_k=settings.graph_extraction_reconcile_top_k,
                )
                if new_rels:
                    merged = ExtractionResult(
                        entities=merged.entities,
                        relationships=merged.relationships + new_rels,
                    )

            # Transient failure iff EVERY chunk failed transiently. Any
            # partial success means retrying is unlikely to help.
            all_transient = ok_count == 0 and all(transient_flags)
            return ExtractionOutcome(result=merged, transient_failure=all_transient)

        # Legacy single-shot: concatenate chunks and run the old path.
        text = "\n\n".join(non_empty)
        return ExtractionOutcome(
            result=await _extract_entities_single_shot(text),
            transient_failure=False,
        )
    except GroqChatError as exc:
        log.warning("extraction upstream failure (%s): %s", exc.status_code, exc.body)
        return ExtractionOutcome(
            result=ExtractionResult(entities=[], relationships=[]),
            transient_failure=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction unexpected failure: %s", exc)
        return ExtractionOutcome(
            result=ExtractionResult(entities=[], relationships=[]),
            transient_failure=True,
        )
