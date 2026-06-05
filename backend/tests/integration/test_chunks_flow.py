"""Integration: upload → OCR → chunks landed in Postgres + Qdrant + cleanup on delete."""

import io
import time
import uuid

import httpx
import pytest

from tests.integration.conftest import STRONG_PASSWORD, mark_user_verified

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"
QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "mmap_chunks"

LONG_TEXT = (
    "Embeddings test. " + "The quick brown fox jumps over the lazy dog. " * 50 + "End."
).encode()


def unique_email() -> str:
    return f"chunks-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        yield client


@pytest.fixture
def auth(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": STRONG_PASSWORD})
    mark_user_verified(email)
    tok = http.post("/auth/login", json={"email": email, "password": STRONG_PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def wait_for_processed(http, headers, doc_id, *, timeout=120.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = http.get(f"/documents/{doc_id}", headers=headers).json()["status"]
        if status in ("processed", "failed"):
            return status
        time.sleep(0.5)
    return "timeout"


def qdrant_points_for(doc_id: str) -> list[dict]:
    r = httpx.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
        json={
            "limit": 1000,
            "with_payload": True,
            "with_vector": False,
            "filter": {"must": [{"key": "document_id", "match": {"value": doc_id}}]},
        },
    )
    return r.json()["result"]["points"]


def upload_text(http, auth, body: bytes, name="ingest.txt") -> dict:
    return http.post(
        "/documents",
        headers=auth,
        files={"file": (name, io.BytesIO(body), "text/plain")},
    ).json()


def test_chunks_land_in_postgres_and_qdrant(http, auth):
    doc = upload_text(http, auth, LONG_TEXT)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"

    chunks = http.get(f"/documents/{doc['id']}/chunks", headers=auth).json()
    assert chunks["total"] >= 2
    # Indexes sequential from 0
    assert [c["chunk_index"] for c in chunks["items"]] == list(range(chunks["total"]))
    # Each chunk's text maps back to original via char_start/char_end
    for c in chunks["items"]:
        assert c["char_end"] > c["char_start"]
        assert len(c["text"]) == c["char_end"] - c["char_start"]

    qdrant_points = qdrant_points_for(doc["id"])
    assert len(qdrant_points) == chunks["total"]
    assert {p["payload"]["chunk_index"] for p in qdrant_points} == {
        c["chunk_index"] for c in chunks["items"]
    }


def test_qdrant_payload_isolates_by_user(http, auth):
    doc = upload_text(http, auth, LONG_TEXT)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"

    me_id = http.get("/auth/me", headers=auth).json()["id"]
    points = qdrant_points_for(doc["id"])
    assert len(points) >= 1
    for p in points:
        assert p["payload"]["user_id"] == me_id
        assert p["payload"]["document_id"] == doc["id"]


def test_chunks_404_for_other_user(http, auth):
    doc = upload_text(http, auth, LONG_TEXT)
    wait_for_processed(http, auth, doc["id"])

    other_email = unique_email()
    httpx.post(
        f"{BASE_URL}/auth/register",
        json={"email": other_email, "password": STRONG_PASSWORD},
    )
    mark_user_verified(other_email)
    other_tok = httpx.post(
        f"{BASE_URL}/auth/login",
        json={"email": other_email, "password": STRONG_PASSWORD},
    ).json()["access_token"]

    r = http.get(
        f"/documents/{doc['id']}/chunks",
        headers={"Authorization": f"Bearer {other_tok}"},
    )
    assert r.status_code == 404


def test_delete_document_removes_chunks_and_qdrant_points(http, auth):
    doc = upload_text(http, auth, LONG_TEXT)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"

    pre = http.get(f"/documents/{doc['id']}/chunks", headers=auth).json()
    assert pre["total"] >= 1
    assert len(qdrant_points_for(doc["id"])) == pre["total"]

    # delete
    assert http.delete(f"/documents/{doc['id']}", headers=auth).status_code == 204

    # Postgres rows cascaded
    follow = http.get(f"/documents/{doc['id']}/chunks", headers=auth)
    assert follow.status_code == 404
    # Qdrant cleaned
    # Wait briefly for the async delete to land
    for _ in range(20):
        if not qdrant_points_for(doc["id"]):
            break
        time.sleep(0.2)
    assert qdrant_points_for(doc["id"]) == []


def test_empty_text_input_produces_zero_chunks(http, auth):
    doc = upload_text(http, auth, b" ")  # single space → empty after strip
    assert wait_for_processed(http, auth, doc["id"]) == "processed"

    chunks = http.get(f"/documents/{doc['id']}/chunks", headers=auth).json()
    assert chunks["total"] == 0
    assert qdrant_points_for(doc["id"]) == []
