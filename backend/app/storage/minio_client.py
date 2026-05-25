from functools import lru_cache
from uuid import UUID

from minio import Minio

from app.core.config import settings


@lru_cache(maxsize=1)
def get_minio_client() -> Minio:
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )


def ensure_bucket(bucket: str | None = None) -> None:
    bucket = bucket or settings.minio_bucket
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def object_storage_key(user_id: UUID, document_id: UUID) -> str:
    return f"users/{user_id}/documents/{document_id}"
