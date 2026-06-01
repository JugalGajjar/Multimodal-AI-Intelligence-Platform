"""arq worker entry-point — `arq app.workers.config.WorkerSettings`."""

from app.workers.queue import QUEUE_NAME, redis_settings
from app.workers.tasks import (
    process_document_ocr,
    reindex_graph_for_document,
    resummarize_document,
)


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
