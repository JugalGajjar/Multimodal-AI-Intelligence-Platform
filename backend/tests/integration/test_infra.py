"""Integration tests that probe every infra service in the compose stack."""

import json

import pytest

from tests.integration.conftest import can_connect, http_get

pytestmark = pytest.mark.integration


def test_postgres_tcp_reachable():
    assert can_connect("127.0.0.1", 5432)


def test_redis_tcp_reachable():
    assert can_connect("127.0.0.1", 6379)


def test_qdrant_collections_endpoint():
    status, body = http_get("http://127.0.0.1:6333/collections")

    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert "collections" in payload["result"]


def test_qdrant_healthz():
    status, body = http_get("http://127.0.0.1:6333/healthz")

    assert status == 200
    assert b"check passed" in body


def test_neo4j_http_browser():
    status, _ = http_get("http://127.0.0.1:7474")

    assert status == 200


def test_neo4j_bolt_port_open():
    assert can_connect("127.0.0.1", 7687)


def test_minio_health_live():
    status, _ = http_get("http://127.0.0.1:9000/minio/health/live")

    assert status == 200


def test_minio_console_reachable():
    status, _ = http_get("http://127.0.0.1:9001")

    assert status in (200, 307)


def test_traefik_dashboard_api():
    status, body = http_get("http://127.0.0.1:8080/api/version")

    assert status == 200
    payload = json.loads(body)
    assert "Version" in payload


def test_traefik_routes_backend_via_host_header():
    req_status, body = http_get_with_host(
        "http://127.0.0.1/api/v1/health", host="api.localhost"
    )

    assert req_status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"


def http_get_with_host(url: str, host: str, timeout: float = 5.0):
    import urllib.request

    req = urllib.request.Request(url, headers={"Host": host})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def test_backend_health_direct():
    status, body = http_get("http://127.0.0.1:8000/api/v1/health")

    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert "version" in payload
    assert "environment" in payload
