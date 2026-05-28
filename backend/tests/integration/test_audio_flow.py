"""Integration: audio upload → Groq Whisper transcribe → chunks + embeddings."""

import io
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = "http://127.0.0.1:8000/api/v1"


def unique_email() -> str:
    return f"audio-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(scope="module")
def sample_wav_bytes() -> bytes:
    """Generate a short macOS-TTS WAV at module scope (so we synthesize once).

    Skips the suite if `say`/`afconvert` aren't available (i.e., non-macOS host).
    """
    if not (Path("/usr/bin/say").exists() and Path("/usr/bin/afconvert").exists()):
        pytest.skip("macOS TTS tools (say/afconvert) not available")

    aiff = Path("/tmp/mmap-test-audio.aiff")
    wav = Path("/tmp/mmap-test-audio.wav")
    subprocess.run(
        [
            "say",
            "-o",
            str(aiff),
            "The platform uses cosine distance and three eighty four dimensional embeddings",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "afconvert",
            str(aiff),
            str(wav),
            "-d",
            "LEI16@22050",
            "-f",
            "WAVE",
        ],
        check=True,
        capture_output=True,
    )
    return wav.read_bytes()


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        yield client


@pytest.fixture
def auth(http):
    email = unique_email()
    http.post("/auth/register", json={"email": email, "password": "abcdefgh"})
    tok = http.post("/auth/login", json={"email": email, "password": "abcdefgh"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {tok}"}


def wait_for_terminal(http, headers, doc_id, *, timeout=120.0) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = http.get(f"/documents/{doc_id}", headers=headers).json()["status"]
        if last in ("processed", "failed"):
            return last
        time.sleep(0.5)
    return last or "timeout"


def test_audio_wav_round_trip(http, auth, sample_wav_bytes):
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("speech.wav", io.BytesIO(sample_wav_bytes), "audio/wav")},
    ).json()
    assert upload["content_type"] == "audio/wav"

    status = wait_for_terminal(http, auth, upload["id"])
    assert status == "processed", f"expected processed, got {status}"

    text = http.get(f"/documents/{upload['id']}/text", headers=auth).json()
    assert text["status"] == "processed"
    assert text["extracted_text"] is not None
    transcript = text["extracted_text"].lower()
    # Whisper transcripts vary slightly; accept either spelled-out or numeric.
    assert "platform" in transcript or "cosine" in transcript

    chunks = http.get(f"/documents/{upload['id']}/chunks", headers=auth).json()
    assert chunks["total"] >= 1, "transcript should chunk + embed like text"


def test_audio_chunks_land_in_qdrant_with_user_isolation(http, auth, sample_wav_bytes):
    upload = http.post(
        "/documents",
        headers=auth,
        files={"file": ("speech-q.wav", io.BytesIO(sample_wav_bytes), "audio/wav")},
    ).json()
    assert wait_for_terminal(http, auth, upload["id"]) == "processed"

    # Qdrant should contain points tagged with our user_id.
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
    assert len(points) >= 1
    for p in points:
        assert p["payload"]["user_id"] == me_id
        assert p["payload"]["document_id"] == upload["id"]
