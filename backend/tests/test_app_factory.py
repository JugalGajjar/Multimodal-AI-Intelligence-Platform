from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.main import create_app


def test_create_app_returns_fastapi_instance():
    app = create_app()

    assert isinstance(app, FastAPI)
    assert app.title == "Multimodal AI Intelligence Platform"
    assert app.version == __version__


def test_create_app_mounts_v1_router():
    app = create_app()
    # Newer FastAPI wraps included routers in `_IncludedRouter` objects that
    # don't expose `.path` directly; recurse into nested `.routes` to cover
    # both shapes.
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        nested = getattr(route, "routes", None)
        if nested:
            stack.extend(nested)

    assert "/api/v1/health" in paths


def test_create_app_registers_cors_middleware():
    app = create_app()

    cors_middlewares = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors_middlewares) == 1


def test_cors_preflight_allows_configured_origin(client):
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_get_includes_allow_origin_header(client):
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
