"""add summary columns to documents

Revision ID: a1c4e0d9b8f1
Revises: 773c4dcc93fd
Create Date: 2026-06-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1c4e0d9b8f1"
down_revision: str | None = "773c4dcc93fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("summary_tldr", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "summary_key_points",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "summary_topics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "summary_topics")
    op.drop_column("documents", "summary_key_points")
    op.drop_column("documents", "summary_tldr")
