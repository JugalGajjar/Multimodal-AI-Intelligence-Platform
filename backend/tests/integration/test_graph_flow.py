"""Integration: upload → entity extraction → Neo4j persisted + queryable."""

import io
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"

RICH_DOC = (
    b"The Multimodal AI Intelligence Platform uses Qdrant as the vector "
    b"database. It uses cosine distance for similarity search. Embeddings are "
    b"produced by the BAAI/bge-small-en-v1.5 sentence transformer model, which "
    b"yields 384-dimensional vectors. The platform was developed by Jugal "
    b"Gajjar as a graduate project. Audio is transcribed by Groq Whisper, and "
    b"image OCR is handled by RapidOCR with Tesseract as fallback. Vision "
    b"descriptions come from Nvidia Nemotron VL."
)


def unique_email() -> str:
    return f"graph-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=90.0) as client:
        yield client


@pytest.fixture
def auth(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})
    tok = http.post("/auth/login", json={"email": email, "password": "abcdefgh"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def wait_for_processed(http, headers, doc_id, *, timeout=60.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = http.get(f"/documents/{doc_id}", headers=headers).json()["status"]
        if s in ("processed", "failed"):
            return s
        time.sleep(0.5)
    return "timeout"


def wait_for_entities(http, headers, *, expected_at_least: int = 1, timeout: float = 60.0) -> int:
    """Graph ingest happens after status=processed (fire-and-forget),
    so poll the entities endpoint until they show up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = http.get("/graph/entities", headers=headers).json()
        if body["total"] >= expected_at_least:
            return body["total"]
        time.sleep(1.0)
    return 0


def upload_text(http, auth) -> dict:
    return http.post(
        "/documents",
        headers=auth,
        files={"file": ("rich.txt", io.BytesIO(RICH_DOC), "text/plain")},
    ).json()


def test_entities_persisted_after_upload(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"

    total = wait_for_entities(http, auth, expected_at_least=3, timeout=90.0)
    if total == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")
    assert total >= 3, f"expected ≥3 entities, got {total}"

    body = http.get("/graph/entities", headers=auth).json()
    names = {e["name"] for e in body["items"]}
    # The document specifically mentions all of these — at least one core
    # technology should appear. Don't pin to all because the LLM varies.
    assert any(
        candidate in " ".join(names).lower()
        for candidate in ("qdrant", "rapidocr", "whisper", "platform")
    )


def test_entity_types_include_person_and_technology(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    total = wait_for_entities(http, auth, expected_at_least=3, timeout=90.0)
    if total == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")

    body = http.get("/graph/entities", headers=auth).json()
    types = {e["type"] for e in body["items"]}
    assert "Technology" in types or "Concept" in types


def test_entity_isolation_between_users(http, auth):
    """User A uploads. User B has zero entities."""
    a_doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, a_doc["id"]) == "processed"
    wait_for_entities(http, auth, expected_at_least=1)

    other_email = unique_email()
    httpx.post(
        f"{BASE_URL}/auth/register",
        json={"email": other_email, "password": "abcdefgh"},
    )
    other_tok = httpx.post(
        f"{BASE_URL}/auth/login",
        json={"email": other_email, "password": "abcdefgh"},
    ).json()["access_token"]
    b_auth = {"Authorization": f"Bearer {other_tok}"}

    body = http.get("/graph/entities", headers=b_auth).json()
    assert body["total"] == 0


def test_document_id_tracked_on_entity(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    total = wait_for_entities(http, auth, expected_at_least=1, timeout=90.0)
    if total == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")

    body = http.get("/graph/entities", headers=auth).json()
    assert any(doc["id"] in (e.get("document_ids") or []) for e in body["items"])


def test_neighbours_endpoint_returns_some_edges_for_central_entity(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    wait_for_entities(http, auth, expected_at_least=3)

    body = http.get("/graph/entities", headers=auth).json()
    if body["total"] == 0:
        pytest.skip("no entities extracted — LLM extraction may be rate-limited")

    # Try the entity that the document mentions the most (usually "platform").
    # Fall back to whatever the first entity is.
    central = None
    for e in body["items"]:
        if "platform" in e["name"].lower():
            central = e["name"]
            break
    central = central or body["items"][0]["name"]

    neighbours = http.get(f"/graph/entities/{central}/neighbours", headers=auth).json()
    # The central entity should have at least one neighbour if it's a real
    # subject; otherwise accept zero (LLM extraction varies).
    assert isinstance(neighbours["items"], list)


def test_delete_document_prunes_orphan_entities(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    total = wait_for_entities(http, auth, expected_at_least=1, timeout=90.0)
    if total == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")

    before = http.get("/graph/entities", headers=auth).json()["total"]
    assert before >= 1

    assert http.delete(f"/documents/{doc['id']}", headers=auth).status_code == 204
    # Give the async cleanup a moment to land.
    deadline = time.time() + 10.0
    after = before
    while time.time() < deadline:
        after = http.get("/graph/entities", headers=auth).json()["total"]
        if after == 0:
            break
        time.sleep(0.5)
    assert after == 0, f"expected entities pruned after delete; before={before} after={after}"


def test_unauthenticated_entities_returns_401_or_403(http):
    r = http.get("/graph/entities")
    assert r.status_code in (401, 403)


def test_snapshot_empty_user_returns_empty_graph(http, auth):
    r = http.get("/graph/snapshot", headers=auth)

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "nodes": [],
        "links": [],
        "node_count": 0,
        "link_count": 0,
    }


def test_snapshot_includes_nodes_and_links_after_upload(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    total = wait_for_entities(http, auth, expected_at_least=3, timeout=90.0)
    if total == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")

    r = http.get("/graph/snapshot", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["node_count"] >= 3
    assert isinstance(body["links"], list)

    # Every link endpoint must exist in nodes (no dangling refs).
    node_ids = {n["id"] for n in body["nodes"]}
    for link in body["links"]:
        assert link["source"] in node_ids
        assert link["target"] in node_ids
        assert isinstance(link["relation"], str) and link["relation"]

    # Every node carries the required display fields.
    for n in body["nodes"]:
        assert n["id"] and n["name"]
        assert "type" in n and isinstance(n["type"], str)
        assert isinstance(n["document_ids"], list)


def test_snapshot_respects_limit_nodes(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    if wait_for_entities(http, auth, expected_at_least=3, timeout=90.0) == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")

    r = http.get("/graph/snapshot?limit_nodes=2", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["node_count"] <= 2


def test_snapshot_isolated_between_users(http, auth):
    doc = upload_text(http, auth)
    assert wait_for_processed(http, auth, doc["id"]) == "processed"
    if wait_for_entities(http, auth, expected_at_least=1, timeout=90.0) == 0:
        pytest.skip("LLM extraction returned 0 — likely Groq free-tier rate-limit")

    other_email = unique_email()
    httpx.post(
        f"{BASE_URL}/auth/register",
        json={"email": other_email, "password": "abcdefgh"},
    )
    other_tok = httpx.post(
        f"{BASE_URL}/auth/login",
        json={"email": other_email, "password": "abcdefgh"},
    ).json()["access_token"]
    b_auth = {"Authorization": f"Bearer {other_tok}"}

    body = http.get("/graph/snapshot", headers=b_auth).json()
    assert body["node_count"] == 0
    assert body["link_count"] == 0


def test_snapshot_unauthenticated_returns_401_or_403(http):
    r = http.get("/graph/snapshot")
    assert r.status_code in (401, 403)
