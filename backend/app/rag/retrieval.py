"""Top-K retrieval scoped to the calling user.

Pipeline (all stages opt-out via settings):
  1. Hybrid candidate fetch via Qdrant prefetch + RRF fusion
     - dense:  bge-small-en-v1.5 embedding
     - sparse: BM25-style sparse vector (fastembed Qdrant/bm25)
  2. Cross-encoder rerank (bge-reranker-base) over the fused candidates
  3. Return the top_k by reranker score
"""

import time
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from opentelemetry import trace
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.core.metrics import retrieval_duration_seconds
from app.embeddings import embed_query
from app.storage.qdrant_client import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    get_qdrant_client,
)

_tracer = trace.get_tracer("mmap.retrieval")


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    score: float
    text: str


def _user_filter(user_id: UUID, document_ids: list[UUID] | None) -> qmodels.Filter:
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
    return qmodels.Filter(must=cast(list, must))


def _points_to_chunks(points: list) -> list[RetrievedChunk]:
    out: list[RetrievedChunk] = []
    for hit in points:
        payload = hit.payload or {}
        out.append(
            RetrievedChunk(
                chunk_id=str(payload.get("chunk_id", "")),
                document_id=str(payload.get("document_id", "")),
                chunk_index=int(payload.get("chunk_index", 0)),
                score=float(hit.score),
                text=str(payload.get("text", "")),
            )
        )
    return out


def _candidate_search(
    *, query: str, user_id: UUID, document_ids: list[UUID] | None, limit: int
) -> list[RetrievedChunk]:
    """Hybrid (dense + sparse + RRF) candidate fetch when enabled, falling back
    to dense-only on collection-not-found or sparse encoder failure."""
    client = get_qdrant_client()
    qfilter = _user_filter(user_id, document_ids)
    dense_vec = embed_query(query)

    if settings.hybrid_enabled:
        from app.rag.sparse import SPARSE_VECTOR_NAME, encode_query

        try:
            s_idx, s_val = encode_query(query)
        except Exception:
            s_idx, s_val = [], []

        if s_idx:
            try:
                response = client.query_points(
                    collection_name=COLLECTION_NAME,
                    prefetch=[
                        qmodels.Prefetch(
                            query=dense_vec,
                            using=DENSE_VECTOR_NAME,
                            limit=settings.hybrid_per_branch_k,
                            filter=qfilter,
                        ),
                        qmodels.Prefetch(
                            query=qmodels.SparseVector(indices=s_idx, values=s_val),
                            using=SPARSE_VECTOR_NAME,
                            limit=settings.hybrid_per_branch_k,
                            filter=qfilter,
                        ),
                    ],
                    query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                    limit=limit,
                    with_payload=True,
                )
                return _points_to_chunks(response.points)
            except UnexpectedResponse as exc:
                if getattr(exc, "status_code", None) == 404:
                    return []
                # Schema mismatch or sparse not configured — fall through to dense.

    try:
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vec,
            using=DENSE_VECTOR_NAME,
            limit=limit,
            query_filter=qfilter,
            with_payload=True,
        )
    except UnexpectedResponse as exc:
        if getattr(exc, "status_code", None) == 404:
            return []
        raise
    return _points_to_chunks(response.points)


def retrieve(
    *,
    query: str,
    user_id: UUID,
    top_k: int = 5,
    document_ids: list[UUID] | None = None,
) -> list[RetrievedChunk]:
    start = time.perf_counter()
    try:
        with _tracer.start_as_current_span("retrieval") as span:
            span.set_attribute("retrieval.top_k", top_k)
            span.set_attribute("retrieval.user_id", str(user_id))
            if document_ids:
                span.set_attribute("retrieval.document_filter_count", len(document_ids))
            span.set_attribute("retrieval.hybrid", settings.hybrid_enabled)
            span.set_attribute("retrieval.rerank", settings.rerank_enabled)

            candidate_k = max(top_k, settings.rerank_candidate_k)
            candidates = _candidate_search(
                query=query,
                user_id=user_id,
                document_ids=document_ids,
                limit=candidate_k,
            )
            span.set_attribute("retrieval.candidate_count", len(candidates))

            if settings.rerank_enabled and len(candidates) > 1:
                from app.rag.reranker import rerank

                chunks = rerank(query, candidates, top_k=top_k)
            else:
                chunks = candidates[:top_k]

            span.set_attribute("retrieval.result_count", len(chunks))
            return chunks
    finally:
        retrieval_duration_seconds.observe(time.perf_counter() - start)
