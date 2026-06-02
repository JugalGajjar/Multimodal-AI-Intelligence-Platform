"""Prometheus metric collectors + timing helpers (also open OTel spans)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# When tracing isn't configured, the API default tracer yields no-op spans.
_tracer = trace.get_tracer("mmap.metrics")

# ---------------------------------------------------------------------------
# HTTP — per-route request count + latency.
# ---------------------------------------------------------------------------
http_requests_total = Counter(
    "mmap_http_requests_total",
    "HTTP requests handled, labelled by method, path, status_code.",
    labelnames=("method", "path", "status_code"),
)

http_request_duration_seconds = Histogram(
    "mmap_http_request_duration_seconds",
    "HTTP request latency from middleware entry to response.",
    labelnames=("method", "path"),
    # Buckets cover typical RAG latencies (vector search through LLM streaming).
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# ---------------------------------------------------------------------------
# LangGraph nodes — per-node latency + failure count.
# ---------------------------------------------------------------------------
node_duration_seconds = Histogram(
    "mmap_workflow_node_duration_seconds",
    "Time spent inside a LangGraph node.",
    labelnames=("node",),
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

node_failures_total = Counter(
    "mmap_workflow_node_failures_total",
    "LangGraph nodes that raised an exception.",
    labelnames=("node",),
)

# ---------------------------------------------------------------------------
# LLM calls — per-provider + model + outcome.
# ---------------------------------------------------------------------------
llm_calls_total = Counter(
    "mmap_llm_calls_total",
    "LLM calls made, labelled by provider, model, status_code.",
    labelnames=("provider", "model", "status_code"),
)

llm_call_duration_seconds = Histogram(
    "mmap_llm_call_duration_seconds",
    "Latency of completed LLM calls.",
    labelnames=("provider", "model"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# ---------------------------------------------------------------------------
# Vector retrieval.
# ---------------------------------------------------------------------------
retrieval_duration_seconds = Histogram(
    "mmap_retrieval_duration_seconds",
    "Qdrant query latency from embedding to results.",
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


@contextmanager
def time_node(name: str) -> Iterator[None]:
    """Time a synchronous block of work, attributing it to a node label."""
    start = time.perf_counter()
    with _tracer.start_as_current_span(f"node.{name}") as span:
        try:
            yield
        except Exception as exc:
            node_failures_total.labels(node=name).inc()
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
        finally:
            node_duration_seconds.labels(node=name).observe(time.perf_counter() - start)


@asynccontextmanager
async def time_node_async(name: str) -> AsyncIterator[None]:
    start = time.perf_counter()
    with _tracer.start_as_current_span(f"node.{name}") as span:
        try:
            yield
        except Exception as exc:
            node_failures_total.labels(node=name).inc()
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
        finally:
            node_duration_seconds.labels(node=name).observe(time.perf_counter() - start)


@asynccontextmanager
async def time_llm(provider: str, model: str) -> AsyncIterator[dict]:
    """Record an LLM call's latency and outcome.

    Yields a mutable dict; set `status` to the upstream status code (e.g. 200
    on success, the GroqChatError status_code on failure).
    """
    state: dict = {"status": "200"}
    start = time.perf_counter()
    with _tracer.start_as_current_span(f"llm.{provider}") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", model)
        try:
            yield state
        except Exception as exc:
            if state["status"] == "200":
                state["status"] = "error"
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
        finally:
            span.set_attribute("llm.status_code", str(state["status"]))
            llm_calls_total.labels(
                provider=provider, model=model, status_code=str(state["status"])
            ).inc()
            llm_call_duration_seconds.labels(provider=provider, model=model).observe(
                time.perf_counter() - start
            )


def render_metrics() -> tuple[bytes, str]:
    """Return the prometheus text payload and its content-type."""
    return generate_latest(), CONTENT_TYPE_LATEST
