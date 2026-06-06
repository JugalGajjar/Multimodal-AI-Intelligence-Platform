"""End-to-end document upload flow: register → login → upload → list → get → delete."""

import io
import uuid

import httpx
import pytest

from tests.integration.conftest import STRONG_PASSWORD, mark_user_verified

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


def unique_email() -> str:
    return f"docs-{uuid.uuid4().hex[:12]}@example.com"


# Minimal valid PDF (under 1 KB) — enough to exercise the upload path.
TINY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
    b"xref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000053 00000 n \n"
    b"trailer<</Size 3/Root 1 0 R>>\nstartxref\n95\n%%EOF\n"
)


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        yield client


@pytest.fixture
def auth(http):
    """Register a fresh user and return {'token': ..., 'email': ...}."""
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
    login = http.post(
        "/auth/login",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    ).json()
    return {"token": login["access_token"], "email": email}


def auth_headers(auth):
    return {"Authorization": f"Bearer {auth['token']}"}


def test_upload_returns_201_with_metadata(http, auth):
    r = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("hello.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    )

    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "hello.pdf"
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(TINY_PDF)
    assert body["status"] == "uploaded"
    assert "id" in body and "created_at" in body
    assert "storage_key" not in body  # internal, not exposed


def test_upload_rejects_unauthenticated(http):
    r = http.post(
        "/documents",
        files={"file": ("x.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    )
    assert r.status_code in (401, 403)


def test_upload_rejects_unsupported_mime(http, auth):
    r = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("x.exe", io.BytesIO(b"\x00\x01"), "application/x-msdownload")},
    )
    assert r.status_code == 415


def test_upload_rejects_empty_file(http, auth):
    r = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert r.status_code == 400


def test_list_returns_only_owned_documents(http, auth):
    # Upload two docs as auth user
    for i in range(2):
        http.post(
            "/documents",
            headers=auth_headers(auth),
            files={
                "file": (
                    f"doc-{i}.pdf",
                    io.BytesIO(TINY_PDF),
                    "application/pdf",
                )
            },
        )

    # Other user — registers and uploads one
    other_email = unique_email()
    http.post(
        "/auth/register",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    mark_user_verified(other_email)
    other_login = http.post(
        "/auth/login",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    ).json()
    http.post(
        "/documents",
        headers={"Authorization": f"Bearer {other_login['access_token']}"},
        files={"file": ("other.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    )

    r = http.get("/documents", headers=auth_headers(auth))

    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    assert all(item["filename"].startswith("doc-") for item in body["items"][:2])


def test_get_one_returns_doc(http, auth):
    upload = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("getme.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    ).json()
    doc_id = upload["id"]

    r = http.get(f"/documents/{doc_id}", headers=auth_headers(auth))

    assert r.status_code == 200
    assert r.json()["id"] == doc_id


def test_get_other_users_doc_returns_404(http, auth):
    # Upload as `auth`
    upload = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("private.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    ).json()
    doc_id = upload["id"]

    # Other user
    other_email = unique_email()
    http.post(
        "/auth/register",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    mark_user_verified(other_email)
    other_login = http.post(
        "/auth/login",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    ).json()

    r = http.get(
        f"/documents/{doc_id}",
        headers={"Authorization": f"Bearer {other_login['access_token']}"},
    )

    assert r.status_code == 404


def test_delete_removes_document(http, auth):
    upload = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("byebye.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    ).json()
    doc_id = upload["id"]

    r = http.delete(f"/documents/{doc_id}", headers=auth_headers(auth))
    assert r.status_code == 204

    follow = http.get(f"/documents/{doc_id}", headers=auth_headers(auth))
    assert follow.status_code == 404


def test_delete_other_users_doc_returns_404(http, auth):
    upload = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("mine.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    ).json()

    other_email = unique_email()
    http.post(
        "/auth/register",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    mark_user_verified(other_email)
    other_login = http.post(
        "/auth/login",
        json={
            "email": other_email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    ).json()

    r = http.delete(
        f"/documents/{upload['id']}",
        headers={"Authorization": f"Bearer {other_login['access_token']}"},
    )
    assert r.status_code == 404


def test_uploaded_object_actually_lands_in_minio(http, auth):
    from minio import Minio

    upload = http.post(
        "/documents",
        headers=auth_headers(auth),
        files={"file": ("verify.pdf", io.BytesIO(TINY_PDF), "application/pdf")},
    ).json()
    doc_id = upload["id"]

    # Reconstruct the storage key (must match service layer's pattern)
    me = http.get("/auth/me", headers=auth_headers(auth)).json()
    expected_key = f"users/{me['id']}/documents/{doc_id}"

    client = Minio(
        endpoint="127.0.0.1:9000",
        access_key="minioadmin",
        secret_key="minioadmin_dev",
        secure=False,
    )
    stat = client.stat_object("mmap-uploads", expected_key)
    assert stat.size == len(TINY_PDF)
