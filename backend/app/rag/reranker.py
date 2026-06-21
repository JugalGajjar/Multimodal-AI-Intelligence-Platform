"""Cross-encoder reranker for the final retrieval stage.

The vector + BM25 hybrid step casts a wide net. The cross-encoder reads each
(query, chunk) pair together and produces a sharper relevance score that
pushes meaningful chunks to the top and demotes lexical near-misses.
"""

import logging
import time
from threading import Lock

from app.core.config import settings
from app.rag.retrieval import RetrievedChunk

log = logging.getLogger("mmap.reranker")

_model_lock = Lock()
_model = None


def get_reranker():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

                last: Exception | None = None
                for attempt in range(1, 6):
                    try:
                        _model = CrossEncoder(settings.rerank_model)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last = exc
                        if attempt == 5:
                            break
                        backoff = attempt * 5
                        log.warning(
                            "reranker load failed (attempt %d/5): %s — retry in %ds",
                            attempt,
                            exc,
                            backoff,
                        )
                        time.sleep(backoff)
                if _model is None:
                    raise RuntimeError(
                        f"could not load reranker after 5 attempts: {last}"
                    ) from last
    return _model


def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    """Return the top_k candidates by cross-encoder score.

    Best-effort — on any model failure the original ordering is preserved
    so a transient HF or ONNX error never kills a chat turn.
    """
    if not candidates:
        return []
    if len(candidates) == 1:
        return candidates[:top_k]

    try:
        model = get_reranker()
        pairs = [(query, c.text) for c in candidates]
        scores = model.predict(pairs)
    except Exception as exc:  # noqa: BLE001
        log.warning("rerank failed; falling back to vector order: %s", exc)
        return candidates[:top_k]

    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda x: -float(x[1]),
    )[:top_k]
    return [
        RetrievedChunk(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            chunk_index=c.chunk_index,
            score=float(s),
            text=c.text,
        )
        for c, s in ranked
    ]
