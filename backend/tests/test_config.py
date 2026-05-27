import importlib

import pytest


@pytest.fixture
def fresh_settings(monkeypatch):
    """Reload the settings module with a clean env so each test is isolated."""

    def _reload(env: dict[str, str] | None = None):
        monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
        for k in (
            "APP_ENV",
            "APP_DEBUG",
            "JWT_SECRET",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "REDIS_HOST",
            "REDIS_PORT",
            "QDRANT_HOST",
            "QDRANT_PORT",
            "MINIO_ENDPOINT",
        ):
            monkeypatch.delenv(k, raising=False)
        if env:
            for k, v in env.items():
                monkeypatch.setenv(k, v)
        import app.core.config as cfg

        cfg.get_settings.cache_clear()
        return importlib.reload(cfg).Settings(_env_file=None)

    return _reload


def test_defaults(fresh_settings):
    s = fresh_settings({})

    assert s.app_env == "development"
    assert s.app_debug is True
    assert s.backend_host == "0.0.0.0"
    assert s.backend_port == 8000
    assert s.jwt_algorithm == "HS256"
    assert s.qdrant_host == "qdrant"
    assert s.neo4j_uri.startswith("bolt://")


def test_cors_origins_parses_csv(fresh_settings):
    s = fresh_settings({"BACKEND_CORS_ORIGINS": "http://localhost:3000, https://app.example.com"})

    assert s.cors_origins == [
        "http://localhost:3000",
        "https://app.example.com",
    ]


def test_cors_origins_empty(fresh_settings):
    s = fresh_settings({"BACKEND_CORS_ORIGINS": ""})

    assert s.cors_origins == []


def test_postgres_dsn_format(fresh_settings):
    s = fresh_settings(
        {
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
            "POSTGRES_HOST": "h",
            "POSTGRES_PORT": "5433",
            "POSTGRES_DB": "d",
        }
    )

    assert s.postgres_dsn == "postgresql+asyncpg://u:p@h:5433/d"


def test_redis_url_format(fresh_settings):
    s = fresh_settings({"REDIS_HOST": "h", "REDIS_PORT": "6380"})

    assert s.redis_url == "redis://h:6380/0"


def test_unknown_env_vars_ignored(fresh_settings):
    s = fresh_settings({"COMPLETELY_RANDOM_VAR": "x"})

    assert not hasattr(s, "completely_random_var")
