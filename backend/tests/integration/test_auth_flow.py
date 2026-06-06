"""Full register → verify → login → /me flow against the live backend + Postgres."""

import uuid

import httpx
import pytest

from tests.integration.conftest import STRONG_PASSWORD, mark_user_verified

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
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 201
    body = r.json()
    # /register now returns a verification-pending response, not the user row.
    assert body["email"] == email
    assert "verification_sent" in body
    assert isinstance(body["verification_sent"], bool)
    assert "message" in body
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_rejects_duplicate_email(http):
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

    r = http.post(
        "/auth/register",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 409


def test_register_rejects_short_password(http):
    r = http.post(
        "/auth/register",
        json={
            "email": unique_email(),
            "password": "short",
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 422


def test_register_rejects_weak_password(http):
    # All-lowercase, missing classes — should fail the validator.
    r = http.post(
        "/auth/register",
        json={
            "email": unique_email(),
            "password": "abcdefghij",
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert r.status_code == 422


def test_register_rejects_disposable_domain(http):
    r = http.post(
        "/auth/register",
        json={
            "email": f"foo-{uuid.uuid4().hex[:6]}@mailinator.com",
            "password": STRONG_PASSWORD,
        },
    )
    assert r.status_code == 400


def test_register_rejects_bad_email(http):
    r = http.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 422


def test_login_rejects_unverified(http):
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

    # Without the verify step the account stays is_verified=false → 403.
    r = http.post(
        "/auth/login",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 403


def test_login_returns_bearer_token(http):
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

    r = http.post(
        "/auth/login",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20


def test_login_rejects_wrong_password(http):
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

    r = http.post(
        "/auth/login",
        json={"email": email, "password": "WRONGPASS", "first_name": "Test", "last_name": "User"},
    )

    assert r.status_code == 401


def test_login_rejects_unknown_email(http):
    r = http.post(
        "/auth/login",
        json={
            "email": unique_email(),
            "password": STRONG_PASSWORD,
            "first_name": "Test",
            "last_name": "User",
        },
    )

    assert r.status_code == 401


def test_me_returns_current_user(http):
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
    token = login["access_token"]

    r = http.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email
    assert body["is_verified"] is True
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


def test_forgot_password_returns_generic_message(http):
    # Even for an unknown email, response must be the same generic shape —
    # otherwise the endpoint leaks which accounts exist.
    r = http.post("/auth/forgot-password", json={"email": unique_email()})
    assert r.status_code == 200
    assert "message" in r.json()


def test_resend_verification_returns_generic_message(http):
    r = http.post("/auth/resend-verification", json={"email": unique_email()})
    assert r.status_code == 200
    assert "message" in r.json()


def test_verify_email_rejects_bad_code(http):
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

    r = http.post(
        "/auth/verify-email",
        json={"email": email, "code": "BADCODE1"},
    )
    assert r.status_code == 400
