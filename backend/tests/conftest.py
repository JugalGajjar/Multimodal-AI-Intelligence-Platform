import os

# Docker hostnames don't resolve when pytest runs on the host machine.
# Set host-side equivalents BEFORE app modules import (Settings caches at
# import time). Tests opting into the live stack will hit these.
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("QDRANT_HOST", "127.0.0.1")
os.environ.setdefault("MINIO_ENDPOINT", "127.0.0.1:9000")
os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c
