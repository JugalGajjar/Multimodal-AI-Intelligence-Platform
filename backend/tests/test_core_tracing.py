"""Tests for OpenTelemetry tracing setup and span emission."""

import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core import tracing
from app.core.logging import CorrelationFilter
from app.core.metrics import time_llm, time_node, time_node_async


@pytest.fixture
def captured_spans():
    """Add an in-memory exporter to the current TracerProvider.

    OTel forbids replacing an already-set provider, so we attach a new
    SimpleSpanProcessor onto the existing one for the test's lifetime.
    """
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        # No SDK provider yet (boot order in tests can leave the no-op default).
        provider = TracerProvider()
        # set_tracer_provider warns but doesn't raise if no-op was active.
        trace.set_tracer_provider(provider)

    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    try:
        yield exporter
    finally:
        processor.shutdown()


class TestConfigureTracing:
    def test_idempotent(self, monkeypatch):
        # Reset the module-private flag so we exercise the path twice cleanly.
        monkeypatch.setattr(tracing, "_configured", False)
        tracing.configure_tracing("svc-1")
        first = trace.get_tracer_provider()
        tracing.configure_tracing("svc-2")  # second call should be a no-op
        second = trace.get_tracer_provider()
        assert first is second

    def test_disabled_setting_skips_provider_install(self, monkeypatch):
        monkeypatch.setattr(tracing, "_configured", False)
        monkeypatch.setattr(tracing.settings, "otel_enabled", False)
        before = trace.get_tracer_provider()
        tracing.configure_tracing("svc-noop")
        after = trace.get_tracer_provider()
        assert before is after


class TestTimeNodeSpans:
    def test_time_node_emits_a_span(self, captured_spans):
        with time_node("classify"):
            pass
        spans = captured_spans.get_finished_spans()
        names = [s.name for s in spans]
        assert "node.classify" in names

    def test_time_node_records_exception_on_span(self, captured_spans):
        with pytest.raises(RuntimeError), time_node("boom"):
            raise RuntimeError("kaboom")
        node_spans = [s for s in captured_spans.get_finished_spans() if s.name == "node.boom"]
        assert len(node_spans) == 1
        assert node_spans[0].status.status_code.name == "ERROR"

    @pytest.mark.asyncio
    async def test_time_node_async_emits_a_span(self, captured_spans):
        async with time_node_async("respond"):
            pass
        assert any(s.name == "node.respond" for s in captured_spans.get_finished_spans())


class TestTimeLlmSpans:
    @pytest.mark.asyncio
    async def test_emits_span_with_provider_and_model_attributes(self, captured_spans):
        async with time_llm("groq", "gpt-x"):
            pass
        spans = [s for s in captured_spans.get_finished_spans() if s.name == "llm.groq"]
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})
        assert attrs.get("llm.provider") == "groq"
        assert attrs.get("llm.model") == "gpt-x"
        assert attrs.get("llm.status_code") == "200"

    @pytest.mark.asyncio
    async def test_records_caller_set_status_on_span(self, captured_spans):
        with pytest.raises(RuntimeError):
            async with time_llm("groq", "rate-x") as state:
                state["status"] = 429
                raise RuntimeError("rate")
        spans = [s for s in captured_spans.get_finished_spans() if s.name == "llm.groq"]
        assert len(spans) == 1
        attrs = dict(spans[0].attributes or {})
        assert attrs.get("llm.status_code") == "429"
        assert spans[0].status.status_code.name == "ERROR"


class TestCorrelationFilterTraceContext:
    def test_attaches_trace_and_span_id_when_active(self, captured_spans):
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("outer"):
            record = logging.LogRecord(
                name="x",
                level=logging.INFO,
                pathname="x",
                lineno=1,
                msg="hi",
                args=(),
                exc_info=None,
            )
            CorrelationFilter().filter(record)
            assert isinstance(record.trace_id, str) and len(record.trace_id) == 32
            assert isinstance(record.span_id, str) and len(record.span_id) == 16

    def test_returns_none_when_no_span_is_active(self):
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname="x",
            lineno=1,
            msg="hi",
            args=(),
            exc_info=None,
        )
        CorrelationFilter().filter(record)
        # Outside a span, these are None.
        assert record.trace_id is None
        assert record.span_id is None
