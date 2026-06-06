"""Qdrant client + collection bootstrap."""

import logging
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings

log = logging.getLogger(__name__)

COLLECTION_NAME = "mmap_chunks"
VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5

# Qdrant Cloud refuses payload filters without an index. Self-hosted is
# lenient — these two fields are what we always filter on.
_INDEXED_PAYLOAD_FIELDS: tuple[tuple[str, qmodels.PayloadSchemaType], ...] = (
    ("user_id", qmodels.PayloadSchemaType.KEYWORD),
    ("document_id", qmodels.PayloadSchemaType.KEYWORD),
)


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    if settings.qdrant_url:
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )
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

    # Idempotent — Qdrant returns a benign error if the index already exists.
    for field_name, schema in _INDEXED_PAYLOAD_FIELDS:
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=schema,
            )
        except UnexpectedResponse as exc:
            # 4xx with "already exists" is fine; re-raise anything else.
            if "already exists" not in str(exc).lower():
                log.warning("payload index create failed for %s: %s", field_name, exc)


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
