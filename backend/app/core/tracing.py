"""OpenTelemetry trace setup. Exports OTLP/gRPC to Jaeger by default."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import settings

log = logging.getLogger("mmap.tracing")

_configured = False


def configure_tracing(service_name: str | None = None) -> None:
    """Install a TracerProvider + OTLP exporter. Idempotent."""
    global _configured
    if _configured:
        return
    if not settings.otel_enabled:
        # Leave the SDK's no-op provider in place; spans become free no-ops.
        _configured = True
        return

    resource = Resource.create({SERVICE_NAME: service_name or settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    try:
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception as exc:  # noqa: BLE001
        # Don't fail boot if the collector is unreachable; just skip exporting.
        log.warning("OTLP exporter init failed: %s — spans will not be exported", exc)

    trace.set_tracer_provider(provider)

    # HTTPX instrumentation is library-wide and idempotent.
    try:
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        log.warning("HTTPX instrumentation failed: %s", exc)

    _configured = True


def get_tracer(name: str = "mmap") -> trace.Tracer:
    return trace.get_tracer(name)
