"""Local embeddings via sentence-transformers (BAAI/bge-small-en-v1.5)."""

import logging
import time
from threading import Lock

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

log = logging.getLogger("mmap.embeddings")

_model_lock = Lock()
_model = None


def get_embedding_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import (  # type: ignore[import-not-found]
                    SentenceTransformer,
                )

                # Retry on HF transient errors (429s, DNS, connection resets).
                # First job pays the load cost; subsequent jobs hit the cache.
                last_err: Exception | None = None
                for attempt in range(1, 6):
                    try:
                        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = exc
                        if attempt == 5:
                            break
                        backoff = attempt * 5
                        log.warning(
                            "embedding model load failed (attempt %d/5): %s — retrying in %ds",
                            attempt,
                            exc,
                            backoff,
                        )
                        time.sleep(backoff)
                if _model is None:
                    raise RuntimeError(
                        f"could not load embedding model after 5 attempts: {last_err}"
                    ) from last_err
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    # Each vector has length EMBEDDING_DIM and is L2-normalized.
    if not texts:
        return []
    model = get_embedding_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [vec.tolist() for vec in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
