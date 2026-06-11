"""Chat-settings endpoints: defaults, partial PATCH, validation."""

import uuid

import httpx
import pytest

from tests.integration.conftest import STRONG_PASSWORD, mark_user_verified

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        yield client


@pytest.fixture
def auth(http) -> dict[str, str]:
    email = f"settings-{uuid.uuid4().hex[:12]}@example.com"
    http.post(
        "/auth/register",
        json={
            "email": email,
            "password": STRONG_PASSWORD,
            "first_name": "Set",
            "last_name": "Tings",
        },
    )
    mark_user_verified(email)
    login = http.post("/auth/login", json={"email": email, "password": STRONG_PASSWORD}).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_settings_default_to_strict_and_5(http, auth):
    r = http.get("/auth/settings", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"rag_mode": "strict", "web_max_results": 5}


def test_patch_updates_only_provided_fields(http, auth):
    r = http.patch("/auth/settings", headers=auth, json={"rag_mode": "regular"})
    assert r.status_code == 200
    assert r.json() == {"rag_mode": "regular", "web_max_results": 5}

    r = http.patch("/auth/settings", headers=auth, json={"web_max_results": 9})
    assert r.status_code == 200
    assert r.json() == {"rag_mode": "regular", "web_max_results": 9}

    # Persisted — survives a fresh GET.
    r = http.get("/auth/settings", headers=auth)
    assert r.json() == {"rag_mode": "regular", "web_max_results": 9}


def test_patch_rejects_out_of_range_and_bad_mode(http, auth):
    assert (
        http.patch("/auth/settings", headers=auth, json={"web_max_results": 11}).status_code == 422
    )
    assert (
        http.patch("/auth/settings", headers=auth, json={"web_max_results": 0}).status_code == 422
    )
    assert http.patch("/auth/settings", headers=auth, json={"rag_mode": "loose"}).status_code == 422


def test_settings_require_auth(http):
    assert http.get("/auth/settings").status_code in (401, 403)
    assert http.patch("/auth/settings", json={"rag_mode": "regular"}).status_code in (401, 403)
