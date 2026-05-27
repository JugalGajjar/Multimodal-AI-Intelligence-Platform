"""Top-K vector retrieval from Qdrant, scoped to the calling user."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from app.embeddings import embed_query
from app.storage.qdrant_client import COLLECTION_NAME, get_qdrant_client


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    score: float
    text: str


def retrieve(
    *,
    query: str,
    user_id: UUID,
    top_k: int = 5,
    document_ids: list[UUID] | None = None,
) -> list[RetrievedChunk]:
    """Embed the query and search Qdrant. Always filters by user_id.

    Returns an empty list if the user has no indexed chunks (or if no hits
    match the optional document_id filter).
    """
    vector = embed_query(query)

    must: list[qmodels.Condition] = [
        qmodels.FieldCondition(
            key="user_id",
            match=qmodels.MatchValue(value=str(user_id)),
        )
    ]
    if document_ids:
        must.append(
            qmodels.FieldCondition(
                key="document_id",
                match=qmodels.MatchAny(any=[str(d) for d in document_ids]),
            )
        )

    client = get_qdrant_client()
    try:
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=top_k,
            query_filter=qmodels.Filter(must=cast(list, must)),
            with_payload=True,
        )
    except UnexpectedResponse as exc:
        # Collection-not-found (404) on a fresh stack with no ingests is a
        # benign empty-result, not an error. Other 4xx/5xx is real.
        if getattr(exc, "status_code", None) == 404:
            return []
        raise

    chunks: list[RetrievedChunk] = []
    for hit in response.points:
        payload = hit.payload or {}
        chunks.append(
            RetrievedChunk(
                chunk_id=str(payload.get("chunk_id", "")),
                document_id=str(payload.get("document_id", "")),
                chunk_index=int(payload.get("chunk_index", 0)),
                score=float(hit.score),
                text=str(payload.get("text", "")),
            )
        )
    return chunks
