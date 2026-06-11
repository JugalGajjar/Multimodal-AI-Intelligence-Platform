"""add chat settings to users

Revision ID: e7b4a2d8c1f9
Revises: d8a3f1c2e9b5
Create Date: 2026-06-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b4a2d8c1f9"
down_revision: str | None = "d8a3f1c2e9b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("rag_mode", sa.String(length=16), nullable=False, server_default="strict"),
    )
    op.add_column(
        "users",
        sa.Column("web_max_results", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade() -> None:
    op.drop_column("users", "web_max_results")
    op.drop_column("users", "rag_mode")
