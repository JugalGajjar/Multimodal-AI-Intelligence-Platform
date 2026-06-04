"""Helpers used by the API to enqueue background jobs into Redis (arq)."""

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

QUEUE_NAME = "mmap-ocr"


def redis_settings() -> RedisSettings:
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        ssl=settings.redis_secure,
    )


async def get_arq_pool() -> ArqRedis:
    return await create_pool(redis_settings(), default_queue_name=QUEUE_NAME)
