"""Adaptive frame sampling for video ingest. Worker-only (uses OpenCV)."""

import logging

log = logging.getLogger("mmap.video.frames")


def probe_video_duration(path: str) -> float:
    """Read just the container metadata (no frame decode) and return the
    duration in seconds. Returns 0.0 when fps/frame-count are unreadable —
    callers should treat 0.0 as "unknown", not "empty"."""
    import cv2  # type: ignore[import-not-found]

    video = cv2.VideoCapture(path)
    if not video.isOpened():
        raise RuntimeError(f"could not open video at {path!r}")
    try:
        fps = float(video.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or total_frames <= 0:
            return 0.0
        return total_frames / fps
    finally:
        video.release()


def extract_adaptive_frames(
    path: str,
    *,
    max_frame_budget: int = 30,
    target_width: int = 720,
    jpeg_quality: int = 85,
) -> list[bytes]:
    """Sample frames from `path` with a duration-aware cadence, downscale to
    `target_width`, and JPEG-encode. Returns a list of frame bytes. Assumes
    duration ≤ 300s — callers enforce the cap upstream."""

    # Lazy import: cv2 (opencv-python-headless) lives in the worker image only.
    import cv2  # type: ignore[import-not-found]

    video = cv2.VideoCapture(path)
    if not video.isOpened():
        raise RuntimeError(f"could not open video at {path!r}")

    try:
        fps = float(video.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or total_frames <= 0:
            log.info("video frames: empty stream (fps=%.2f frames=%d)", fps, total_frames)
            return []

        duration = total_frames / fps

        # Adaptive bucket sampling tuned to keep token cost bounded while
        # preserving temporal resolution on short clips. The ≤300s tier is
        # the terminal branch — duration is bounded upstream by the
        # `video_max_duration_sec` cap.
        if duration <= 60:
            step = max(1, int(fps))
        elif duration <= 120:
            step = max(1, int(fps * 2))
        else:
            step = max(1, int(fps * 5))

        indices = list(range(0, total_frames, step))

        # Hard ceiling — downsample uniformly if the cadence still overshoots.
        if len(indices) > max_frame_budget:
            stride = len(indices) / max_frame_budget
            indices = [indices[int(i * stride)] for i in range(max_frame_budget)]

        log.info(
            "video frames: duration=%.1fs fps=%.1f step=%d sampled=%d",
            duration,
            fps,
            step,
            len(indices),
        )

        out: list[bytes] = []
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]

        for idx in indices:
            video.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = video.read()
            if not ok:
                continue

            h, w = frame.shape[:2]
            if w > target_width:
                scale = target_width / w
                frame = cv2.resize(
                    frame,
                    (target_width, int(h * scale)),
                    interpolation=cv2.INTER_AREA,
                )

            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if ok:
                out.append(bytes(buf))

        return out
    finally:
        video.release()
