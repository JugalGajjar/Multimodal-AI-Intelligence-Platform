"""Full register → login → /me flow against the live backend + Postgres."""

import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        yield client


def test_register_creates_user(http):
    email = unique_email()

    r = http.post(
        "/auth/register",
        json={"email": email, "password": "abcdefgh"},
    )

    assert r.status_code == 201
    body = r.json()
    assert body["email"] == email
    assert "id" in body
    assert "created_at" in body
    assert "hashed_password" not in body
    assert "password" not in body


def test_register_rejects_duplicate_email(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})

    r = http.post(
        "/auth/register",
        json={"email": email, "password": "abcdefgh"},
    )

    assert r.status_code == 409


def test_register_rejects_short_password(http):
    r = http.post(
        "/auth/register",
        json={"email": unique_email(), "password": "short"},
    )

    assert r.status_code == 422


def test_register_rejects_bad_email(http):
    r = http.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "abcdefgh"},
    )

    assert r.status_code == 422


def test_login_returns_bearer_token(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})

    r = http.post("/auth/login", json={"email": email, "password": "abcdefgh"})

    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20


def test_login_rejects_wrong_password(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})

    r = http.post("/auth/login", json={"email": email, "password": "WRONGPASS"})

    assert r.status_code == 401


def test_login_rejects_unknown_email(http):
    r = http.post(
        "/auth/login",
        json={"email": unique_email(), "password": "abcdefgh"},
    )

    assert r.status_code == 401


def test_me_returns_current_user(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})
    login = http.post(
        "/auth/login", json={"email": email, "password": "abcdefgh"}
    ).json()
    token = login["access_token"]

    r = http.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email
    assert "id" in body
    assert "hashed_password" not in body


def test_me_rejects_missing_token(http):
    r = http.get("/auth/me")

    # FastAPI's HTTPBearer returns 403 by default; we use auto_error=True which
    # returns 403 in older versions and 401 in newer FastAPI — accept either.
    assert r.status_code in (401, 403)


def test_me_rejects_invalid_token(http):
    r = http.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert r.status_code == 401


def test_me_rejects_token_signed_with_wrong_secret(http):
    import jwt

    bad_token = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000"},
        "wrong-secret",
        algorithm="HS256",
    )

    r = http.get("/auth/me", headers={"Authorization": f"Bearer {bad_token}"})

    assert r.status_code == 401
