"""add chat_model to users

Revision ID: a2f9e6d1c8b3
Revises: f3c8d1a7b2e4
Create Date: 2026-07-04 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2f9e6d1c8b3"
down_revision: str | None = "f3c8d1a7b2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL means "use the app-wide default" — that keeps every existing user
    # on the current behavior until they explicitly pick a model in Settings.
    op.add_column(
        "users",
        sa.Column("chat_model", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "chat_model")
