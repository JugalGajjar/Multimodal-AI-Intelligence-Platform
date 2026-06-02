"""arq worker entry-point — `arq app.workers.config.WorkerSettings`."""

from app.core.config import settings
from app.core.logging import configure_logging
from app.workers.queue import QUEUE_NAME, redis_settings
from app.workers.tasks import (
    process_document_ocr,
    reindex_graph_for_document,
    resummarize_document,
)


async def _on_startup(_ctx: dict) -> None:
    configure_logging("DEBUG" if settings.app_debug else "INFO")


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
    job_timeout = 300  # 5 min per job
    on_startup = _on_startup
