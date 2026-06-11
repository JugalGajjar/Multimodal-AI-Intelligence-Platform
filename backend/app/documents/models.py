from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        String(32), nullable=False, default=DocumentStatus.UPLOADED
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Set by the worker on the FAILED path so the UI can surface *why* a
    # document failed (e.g. "Video must be under 5 minutes"). Null on
    # success and on legacy FAILED rows from before this column existed.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Populated by the summarization agent; null when no summary has been
    # generated or stored yet.
    summary_tldr: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_key_points: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    summary_topics: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship(lazy="noload")

    @property
    def summary(self) -> dict[str, Any] | None:
        if not self.summary_tldr and not self.summary_key_points and not self.summary_topics:
            return None
        return {
            "tldr": self.summary_tldr or "",
            "key_points": list(self.summary_key_points or []),
            "topics": list(self.summary_topics or []),
        }
