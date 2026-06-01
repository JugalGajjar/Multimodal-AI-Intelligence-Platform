"""Qdrant client + collection bootstrap."""

from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import settings

COLLECTION_NAME = "mmap_chunks"
VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection() -> None:
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=VECTOR_SIZE,
                distance=qmodels.Distance.COSINE,
            ),
        )


def delete_points_for_document(document_id: str) -> None:
    client = get_qdrant_client()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchValue(value=document_id),
                    )
                ]
            )
        ),
    )
