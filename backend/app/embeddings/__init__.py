"""Local embeddings via sentence-transformers.

`BAAI/bge-small-en-v1.5` → 384-dim float32 vectors. Singleton model, loaded
on first call. The sentence-transformers import is lazy so this module is
safe to import in environments where the package isn't installed yet
(empty-input path still works).
"""

from threading import Lock

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

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

                _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts; returns float32 lists of length EMBEDDING_DIM."""
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
    """Convenience: embed a single query string and return one vector."""
    return embed_texts([text])[0]
