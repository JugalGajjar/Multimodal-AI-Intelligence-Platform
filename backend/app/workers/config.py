"""arq worker entry-point — `arq app.workers.config.WorkerSettings`."""

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing
from app.workers.queue import QUEUE_NAME, redis_settings
from app.workers.tasks import (
    process_document_ocr,
    reindex_graph_for_document,
    resummarize_document,
)


async def _on_startup(_ctx: dict) -> None:
    configure_logging("DEBUG" if settings.app_debug else "INFO")
    configure_tracing("mmap-worker")


class WorkerSettings:
    functions = [
        process_document_ocr,
        reindex_graph_for_document,
        resummarize_document,
    ]
    redis_settings = redis_settings()
    queue_name = QUEUE_NAME
    keep_result_forever = False
    keep_result = 60
    max_jobs = 4
    # 10 min per job — scan-heavy PDFs and long audio files push OCR / Whisper
    # past 5 min. The tasks catch CancelledError so a timeout still surfaces
    # to the user as status=failed with a helpful error_message.
    job_timeout = 600
    # arq polls Redis at this interval to check for new jobs; idle workers
    # still pay per poll. Default 0.5s = ~5M req/mo, far over Upstash's
    # 500K free tier. 6.5s = ~399K/mo (~20% headroom) with ~6.5s worst-case
    # enqueue→pickup latency (invisible against the 30s+ OCR pipeline).
    poll_delay = 6.5
    on_startup = _on_startup
