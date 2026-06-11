"""add error_message to documents

Revision ID: d8a3f1c2e9b5
Revises: c5d7e2a9b1f4
Create Date: 2026-06-10 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8a3f1c2e9b5"
down_revision: str | None = "c5d7e2a9b1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "error_message")
