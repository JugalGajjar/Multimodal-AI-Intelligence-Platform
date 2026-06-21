"""BM25-style sparse vectors via fastembed, used for the lexical branch of
hybrid retrieval. Qdrant fuses the dense and sparse branches with RRF."""

import logging
import time
from threading import Lock

log = logging.getLogger("mmap.sparse")

SPARSE_MODEL_NAME = "Qdrant/bm25"
SPARSE_VECTOR_NAME = "bm25"

_model_lock = Lock()
_model = None


def get_sparse_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from fastembed import SparseTextEmbedding  # type: ignore[import-not-found]

                last: Exception | None = None
                for attempt in range(1, 6):
                    try:
                        _model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last = exc
                        if attempt == 5:
                            break
                        backoff = attempt * 5
                        log.warning(
                            "sparse model load failed (attempt %d/5): %s — retry in %ds",
                            attempt,
                            exc,
                            backoff,
                        )
                        time.sleep(backoff)
                if _model is None:
                    raise RuntimeError(
                        f"could not load sparse model after 5 attempts: {last}"
                    ) from last
    return _model


def encode_passages(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    """Encode chunk texts as (indices, values) pairs suitable for
    qdrant_client.models.SparseVector. Order matches input."""
    if not texts:
        return []
    out: list[tuple[list[int], list[float]]] = []
    for emb in get_sparse_model().embed(texts):
        out.append(
            (
                [int(i) for i in emb.indices.tolist()],
                [float(v) for v in emb.values.tolist()],
            )
        )
    return out


def encode_query(text: str) -> tuple[list[int], list[float]]:
    """Encode a query string with the query-side tokenizer."""
    embs = list(get_sparse_model().query_embed([text]))
    if not embs:
        return [], []
    emb = embs[0]
    return (
        [int(i) for i in emb.indices.tolist()],
        [float(v) for v in emb.values.tolist()],
    )
