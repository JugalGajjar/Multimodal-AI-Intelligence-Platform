"""Integration: image upload → OCR + Vision → chunks + embeddings.

Generates a synthetic test PNG with PIL (available in the API container's
deps via sentence-transformers). The vision call hits the real OpenRouter
endpoint — the test tolerates upstream rate-limits so it isn't flaky against
free-tier quotas.
"""

import io
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


def unique_email() -> str:
    return f"img-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(scope="module")
def sample_png_bytes() -> bytes:
    """Build a tiny diagram-style PNG with PIL."""
    try:
        from PIL import Image, ImageDraw  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("Pillow not available in dev venv")

    img = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (400, 40)], fill="#1e40af")
    draw.text((10, 12), "MMAP Test Diagram", fill="white")
    draw.rectangle([(20, 60), (180, 140)], outline="black", width=2)
    draw.text((40, 90), "Block A", fill="black")
    draw.rectangle([(220, 60), (380, 140)], outline="black", width=2)
    draw.text((250, 90), "Block B", fill="black")
    draw.line([(180, 100), (220, 100)], fill="black", width=2)
    draw.text((20, 160), "Caption text below", fill="black")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        yield client


@pytest.fixture
def auth(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})
    tok = http.post("/auth/login", json={"email": email, "password": "abcdefgh"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def wait_for_terminal(http, headers, doc_id, *, timeout=180.0) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = http.get(f"/documents/{doc_id}", headers=headers).json()["status"]
        if last in ("processed", "failed"):
            return last
        time.sleep(0.5)
    return last or "timeout"


def test_image_upload_round_trip(http, auth, sample_png_bytes):
    """Image processes successfully — Vision may be rate-limited, but the
    pipeline must always at least return OCR text (degraded mode)."""
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("diagram.png", io.BytesIO(sample_png_bytes), "image/png")},
    ).json()
    assert upload["content_type"] == "image/png"

    status = wait_for_terminal(http, auth, upload["id"])
    assert status == "processed", f"expected processed, got {status}"

    text_resp = http.get(f"/documents/{upload['id']}/text", headers=auth).json()
    text = text_resp["extracted_text"] or ""
    # OCR section is always there (Tesseract is reliable).
    assert "--- OCR text ---" in text, (
        f"expected OCR section even with vision rate-limited; got: {text[:200]!r}"
    )
    # Some OCR token must have come through (block labels or caption).
    assert any(token in text.lower() for token in ("block", "diagram", "caption", "mmap"))


def test_image_chunks_land_in_qdrant(http, auth, sample_png_bytes):
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("diagram-q.png", io.BytesIO(sample_png_bytes), "image/png")},
    ).json()
    assert wait_for_terminal(http, auth, upload["id"]) == "processed"

    me_id = http.get("/auth/me", headers=auth).json()["id"]
    r = httpx.post(
        "http://127.0.0.1:6333/collections/mmap_chunks/points/scroll",
        json={
            "limit": 100,
            "with_payload": True,
            "with_vector": False,
            "filter": {"must": [{"key": "document_id", "match": {"value": upload["id"]}}]},
        },
    )
    points = r.json()["result"]["points"]
    assert len(points) >= 1, "image should chunk and index even with OCR-only output"
    for p in points:
        assert p["payload"]["user_id"] == me_id
