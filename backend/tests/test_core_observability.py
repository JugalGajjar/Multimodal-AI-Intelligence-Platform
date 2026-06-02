"""Tests for structured logging, request IDs, and Prometheus metrics."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import metrics as metrics_router
from app.core.logging import (
    CorrelationFilter,
    configure_logging,
    request_id_var,
    user_id_var,
)
from app.core.metrics import (
    http_requests_total,
    node_duration_seconds,
    node_failures_total,
    render_metrics,
    time_llm,
    time_node,
    time_node_async,
)
from app.core.middleware import (
    REQUEST_ID_HEADER,
    HttpMetricsMiddleware,
    RequestIdMiddleware,
)


class TestCorrelationFilter:
    def test_attaches_request_and_user_ids_from_contextvars(self):
        request_id_var.set("req-abc")
        user_id_var.set("user-1")
        try:
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
            assert record.request_id == "req-abc"
            assert record.user_id == "user-1"
        finally:
            request_id_var.set(None)
            user_id_var.set(None)

    def test_missing_contextvars_yield_none(self):
        request_id_var.set(None)
        user_id_var.set(None)
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
        assert record.request_id is None
        assert record.user_id is None


class TestConfigureLogging:
    def test_emits_valid_json_with_correlation_fields(self, capsys):
        configure_logging("INFO")
        request_id_var.set("req-zzz")
        user_id_var.set("user-9")
        try:
            logging.getLogger("mmap.observability.test").info("hello world")
        finally:
            request_id_var.set(None)
            user_id_var.set(None)
        out = capsys.readouterr().err or capsys.readouterr().out
        # Pick the last JSON line; pytest may have written other noise around it.
        last = [line for line in out.splitlines() if line.strip().startswith("{")][-1]
        payload = json.loads(last)
        assert payload["message"] == "hello world"
        assert payload["request_id"] == "req-zzz"
        assert payload["user_id"] == "user-9"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "mmap.observability.test"

    def test_replaces_handlers_so_log_lines_are_json(self):
        configure_logging("INFO")
        root = logging.getLogger()
        assert len(root.handlers) == 1


class TestRequestIdMiddleware:
    def _build_app(self) -> FastAPI:
        app = FastAPI()
        # Order matters: HTTP metrics inside, RequestId outside.
        app.add_middleware(HttpMetricsMiddleware)
        app.add_middleware(RequestIdMiddleware)
        app.include_router(metrics_router.router)

        @app.get("/echo-id")
        async def echo_id():
            return {"id": request_id_var.get()}

        return app

    def test_mints_a_new_id_when_no_header(self):
        client = TestClient(self._build_app())
        response = client.get("/echo-id")
        assert response.status_code == 200
        rid = response.headers[REQUEST_ID_HEADER]
        assert rid and len(rid) >= 16
        assert response.json()["id"] == rid

    def test_honors_incoming_request_id(self):
        client = TestClient(self._build_app())
        response = client.get("/echo-id", headers={REQUEST_ID_HEADER: "client-supplied-id"})
        assert response.headers[REQUEST_ID_HEADER] == "client-supplied-id"
        assert response.json()["id"] == "client-supplied-id"


class TestHttpMetricsMiddleware:
    def test_records_counter_and_histogram_per_route(self):
        app = FastAPI()
        app.add_middleware(HttpMetricsMiddleware)
        app.add_middleware(RequestIdMiddleware)

        @app.get("/items/{item_id}")
        async def items(item_id: int):
            return {"id": item_id}

        client = TestClient(app)
        client.get("/items/7")
        client.get("/items/9")

        rendered = render_metrics()[0].decode()
        assert "mmap_http_requests_total" in rendered
        # Route template (not the raw path) is the label so cardinality stays bounded.
        assert 'path="/items/{item_id}"' in rendered

    def test_skips_metrics_endpoint_to_avoid_recursion(self):
        app = FastAPI()
        app.add_middleware(HttpMetricsMiddleware)
        app.include_router(metrics_router.router)
        client = TestClient(app)
        before = http_requests_total._metrics  # type: ignore[attr-defined]
        before_keys = set(before.keys())
        client.get("/metrics")
        after_keys = set(http_requests_total._metrics.keys())  # type: ignore[attr-defined]
        # No new label for the metrics endpoint was added.
        for k in after_keys - before_keys:
            assert k[1] != "/metrics"


class TestNodeTiming:
    def test_time_node_records_duration(self):
        before = sum(
            sample.value
            for sample in node_duration_seconds.collect()[0].samples
            if sample.name == "mmap_workflow_node_duration_seconds_count"
            and sample.labels.get("node") == "test_node"
        )
        with time_node("test_node"):
            pass
        after = sum(
            sample.value
            for sample in node_duration_seconds.collect()[0].samples
            if sample.name == "mmap_workflow_node_duration_seconds_count"
            and sample.labels.get("node") == "test_node"
        )
        assert after == before + 1

    def test_time_node_records_failure(self):
        # `_total` is the counter sample; collect()[0].samples also exposes
        # `_created` (epoch ts) which we must skip.
        def _count():
            return sum(
                s.value
                for s in node_failures_total.collect()[0].samples
                if s.name.endswith("_total") and s.labels.get("node") == "test_failing_node"
            )

        before = _count()
        with pytest.raises(RuntimeError), time_node("test_failing_node"):
            raise RuntimeError("boom")
        assert _count() == before + 1

    @pytest.mark.asyncio
    async def test_time_node_async_records_duration(self):
        before = sum(
            sample.value
            for sample in node_duration_seconds.collect()[0].samples
            if sample.name == "mmap_workflow_node_duration_seconds_count"
            and sample.labels.get("node") == "test_async_node"
        )
        async with time_node_async("test_async_node"):
            pass
        after = sum(
            sample.value
            for sample in node_duration_seconds.collect()[0].samples
            if sample.name == "mmap_workflow_node_duration_seconds_count"
            and sample.labels.get("node") == "test_async_node"
        )
        assert after == before + 1


class TestLlmTiming:
    @pytest.mark.asyncio
    async def test_records_default_status_on_success(self):
        # Caller didn't touch state — it defaults to "200".
        async with time_llm("groq", "test-model"):
            pass
        rendered = render_metrics()[0].decode()
        assert (
            'mmap_llm_calls_total{model="test-model",provider="groq",status_code="200"}' in rendered
        )

    @pytest.mark.asyncio
    async def test_records_caller_set_status_on_failure(self):
        with pytest.raises(RuntimeError):
            async with time_llm("groq", "rate-limited-model") as state:
                state["status"] = 429
                raise RuntimeError("rate limit")
        rendered = render_metrics()[0].decode()
        assert (
            'mmap_llm_calls_total{model="rate-limited-model",provider="groq",status_code="429"}'
            in rendered
        )


class TestMetricsEndpoint:
    def test_returns_prometheus_text_format(self):
        app = FastAPI()
        app.include_router(metrics_router.router)
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        # At least one collector is exposed.
        assert "# TYPE" in response.text
