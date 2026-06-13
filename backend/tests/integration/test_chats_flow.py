"""Chat history flow: stream → persist → list/transcript/rename/search/delete."""

import json
import uuid

import httpx
import pytest

from tests.integration.conftest import STRONG_PASSWORD, mark_user_verified

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


@pytest.fixture
def http():
    # Streaming turns include live Groq calls — generous timeout.
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        yield client


@pytest.fixture
def auth(http) -> dict[str, str]:
    email = f"chats-{uuid.uuid4().hex[:12]}@example.com"
    http.post(
        "/auth/register",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Chat",
            "last_name": "Flow",
        },
    )
    mark_user_verified(email)
    login = http.post("/auth/login", json={"email": email, "password": STRONG_PASSWORD}).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def _stream_turn(http, auth, body: dict) -> dict:
    """POST /chat/stream and parse SSE events into {event: data} (last wins)."""
    events: dict = {}
    with http.stream("POST", "/chat/stream", headers=auth, json=body) as resp:
        if resp.status_code == 503:
            # No Groq key on this stack (CI). The full chat flow needs upstream
            # LLMs; skip rather than fail.
            pytest.skip("Groq not configured on the backend")
        assert resp.status_code == 200
        event_name = ""
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: ") and event_name:
                events[event_name] = json.loads(line[len("data: ") :])
    return events


def test_full_chat_history_flow(http, auth):
    # Turn 1 — no chat_id → server creates the chat.
    distinctive = f"zebra-{uuid.uuid4().hex[:8]}"
    ev1 = _stream_turn(
        http,
        auth,
        {"query": f"Remember this codeword: {distinctive}. What is RAG?", "use_rag": False},
    )
    assert "meta" in ev1 and "done" in ev1, f"events: {list(ev1)}"
    chat_id = ev1["meta"]["chat_id"]
    assert chat_id

    # Turn 2 — same chat.
    ev2 = _stream_turn(
        http,
        auth,
        {"query": "And what does it stand for?", "use_rag": False, "chat_id": chat_id},
    )
    assert ev2["meta"]["chat_id"] == chat_id

    # List: one chat, 4 messages, non-empty title.
    listing = http.get("/chats", headers=auth).json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["id"] == chat_id
    assert item["message_count"] == 4
    assert item["title"].strip()  # placeholder acceptable (Groq best-effort)

    # Transcript ordered user/assistant/user/assistant.
    detail = http.get(f"/chats/{chat_id}", headers=auth).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert distinctive in detail["messages"][0]["content"]

    # Rename.
    renamed = http.patch(
        f"/chats/{chat_id}", headers=auth, json={"title": "My renamed chat"}
    ).json()
    assert renamed["title"] == "My renamed chat"

    # Search by the distinctive codeword from turn 1's question.
    found = http.get("/chats/search", headers=auth, params={"q": distinctive}).json()
    assert found["total"] >= 1
    hit = next(i for i in found["items"] if i["id"] == chat_id)
    assert distinctive in hit["snippet"]
    assert hit["match_source"] == "message"

    # Delete → 204 → transcript 404.
    assert http.delete(f"/chats/{chat_id}", headers=auth).status_code == 204
    assert http.get(f"/chats/{chat_id}", headers=auth).status_code == 404


def test_non_streaming_chat_rejects_chat_id(http, auth):
    """The session-continuation flag is honored only by /chat/stream — silently
    ignoring it on the non-streaming endpoint would lie to the caller."""
    r = http.post(
        "/chat",
        headers=auth,
        json={
            "query": "hello",
            "use_rag": False,
            "chat_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert r.status_code == 400
    assert "stream" in r.json()["detail"].lower()


def test_chat_id_of_other_user_is_404(http, auth):
    ev = _stream_turn(http, auth, {"query": "hello there", "use_rag": False})
    chat_id = ev["meta"]["chat_id"]

    # Second user cannot stream into or read the first user's chat.
    other_email = f"chats2-{uuid.uuid4().hex[:12]}@example.com"
    http.post(
        "/auth/register",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Other",
            "last_name": "User",
        },
    )
    mark_user_verified(other_email)
    other_login = http.post(
        "/auth/login", json={"email": other_email, "password": STRONG_PASSWORD}
    ).json()
    other_auth = {"Authorization": f"Bearer {other_login['access_token']}"}

    r = http.post(
        "/chat/stream",
        headers=other_auth,
        json={"query": "hijack", "use_rag": False, "chat_id": chat_id},
    )
    assert r.status_code == 404
    assert http.get(f"/chats/{chat_id}", headers=other_auth).status_code == 404
