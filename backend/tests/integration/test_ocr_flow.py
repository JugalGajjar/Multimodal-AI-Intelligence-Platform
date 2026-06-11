"""Integration: upload → worker OCR → extracted_text populated."""

import io
import time
import uuid

import httpx
import pytest

from tests.integration.conftest import STRONG_PASSWORD, mark_user_verified

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


def unique_email() -> str:
    return f"ocr-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        yield client


@pytest.fixture
def auth(http):
    email = unique_email()
    http.post(
        "/auth/register",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    mark_user_verified(email)
    tok = http.post(
        "/auth/login",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def wait_for_status(
    http: httpx.Client, headers: dict, doc_id: str, *, timeout: float = 60.0
) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = http.get(f"/documents/{doc_id}", headers=headers).json()["status"]
        if last in ("processed", "failed"):
            return last
        time.sleep(0.5)
    return last or "timeout"


def test_text_plain_round_trip(http, auth):
    body = b"hello from the OCR pipeline\nsecond line"
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("note.txt", io.BytesIO(body), "text/plain")},
    ).json()

    status = wait_for_status(http, auth, upload["id"])
    assert status == "processed"

    text = http.get(f"/documents/{upload['id']}/text", headers=auth).json()
    assert text["status"] == "processed"
    assert text["extracted_text"] is not None
    assert "hello from the OCR pipeline" in text["extracted_text"]
    assert "second line" in text["extracted_text"]


def test_markdown_round_trip(http, auth):
    body = b"# Title\n\nSome body text"
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("doc.md", io.BytesIO(body), "text/markdown")},
    ).json()

    status = wait_for_status(http, auth, upload["id"])
    assert status == "processed"
    assert (
        "Title"
        in http.get(f"/documents/{upload['id']}/text", headers=auth).json()["extracted_text"]
    )


def test_text_endpoint_404_for_other_users_doc(http, auth):
    body = b"private notes"
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("p.txt", io.BytesIO(body), "text/plain")},
    ).json()
    wait_for_status(http, auth, upload["id"])

    # second user
    other_email = unique_email()
    httpx.post(
        f"{BASE_URL}/auth/register",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    mark_user_verified(other_email)
    other_tok = httpx.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    ).json()["access_token"]

    r = http.get(
        f"/documents/{upload['id']}/text",
        headers={"Authorization": f"Bearer {other_tok}"},
    )
    assert r.status_code == 404


def test_audio_upload_with_invalid_bytes_marks_failed(http, auth):
    # Invalid audio bytes should cause Groq Whisper to reject the file and
    # the worker to mark the doc FAILED. Happy path lives in test_audio_flow.
    body = b"fake mp3 bytes"
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("clip.mp3", io.BytesIO(body), "audio/mpeg")},
    ).json()
    status = wait_for_status(http, auth, upload["id"])

    assert status == "failed"
    # error_message is on the main doc response (not /text) so the UI can
    # surface a reason without pulling the full extracted-text payload.
    doc = http.get(f"/documents/{upload['id']}", headers=auth).json()
    assert doc["error_message"] is not None
    assert doc["error_message"] != ""
