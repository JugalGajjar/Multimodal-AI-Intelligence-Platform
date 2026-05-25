from app import __version__


def test_health_endpoint_returns_ok(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert "environment" in body


def test_openapi_schema_available(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Multimodal AI Intelligence Platform"


def test_health_route_in_openapi(client):
    response = client.get("/openapi.json")

    paths = response.json()["paths"]
    assert "/api/v1/health" in paths
