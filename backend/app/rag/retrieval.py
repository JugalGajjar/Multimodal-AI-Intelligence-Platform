"""Top-K vector retrieval from Qdrant, scoped to the calling user."""

import time
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from opentelemetry import trace
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.metrics import retrieval_duration_seconds
from app.embeddings import embed_query
from app.storage.qdrant_client import COLLECTION_NAME, get_qdrant_client

_tracer = trace.get_tracer("mmap.retrieval")


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
    # Always filters by user_id. Empty list when nothing matches.
    start = time.perf_counter()
    try:
        with _tracer.start_as_current_span("retrieval") as span:
            span.set_attribute("retrieval.top_k", top_k)
            span.set_attribute("retrieval.user_id", str(user_id))
            if document_ids:
                span.set_attribute("retrieval.document_filter_count", len(document_ids))

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
                # Collection-not-found on a fresh stack is benign; other errors are not.
                if getattr(exc, "status_code", None) == 404:
                    span.set_attribute("retrieval.result_count", 0)
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
            span.set_attribute("retrieval.result_count", len(chunks))
            return chunks
    finally:
        retrieval_duration_seconds.observe(time.perf_counter() - start)
