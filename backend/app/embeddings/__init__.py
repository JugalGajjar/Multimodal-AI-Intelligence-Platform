"""Local embeddings via sentence-transformers (BAAI/bge-small-en-v1.5)."""

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
