"""Extract the audio track from a video file via ffmpeg. Worker-only."""

import contextlib
import logging
import os
import subprocess
from tempfile import NamedTemporaryFile

log = logging.getLogger("mmap.video.audio")


def extract_audio_track(path: str, *, timeout: float = 300.0) -> bytes:
    """Return AAC m4a bytes (mono, 16 kHz, ~64 kbps), or b'' when the video
    has no audio stream or ffmpeg is unavailable. m4a is what Groq Whisper
    accepts and is ~4-8x smaller than 16 kHz mono WAV for the same content,
    which matters on long uploads.

    Uses a temp file rather than pipe:1 because the mp4 container needs
    seekable output to write its moov atom."""

    # Pre-allocate a temp path; close the handle so ffmpeg can write to it.
    with NamedTemporaryFile(suffix=".m4a", delete=False) as tf:
        out_path = tf.name

    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=timeout)
        with open(out_path, "rb") as f:
            return f.read()
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
        log.info("ffmpeg returned %d (likely no audio): %s", exc.returncode, stderr)
        return b""
    except FileNotFoundError:
        log.warning("ffmpeg not installed; skipping video audio extraction")
        return b""
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg timed out extracting audio from %s", path)
        return b""
    finally:
        with contextlib.suppress(OSError):
            os.unlink(out_path)
