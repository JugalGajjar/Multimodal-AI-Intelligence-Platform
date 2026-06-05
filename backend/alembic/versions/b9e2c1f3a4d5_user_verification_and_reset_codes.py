"""add user verification and password reset fields

Revision ID: b9e2c1f3a4d5
Revises: a1c4e0d9b8f1
Create Date: 2026-06-05 13:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9e2c1f3a4d5"
down_revision: Union[str, None] = "a1c4e0d9b8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("verification_code_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("verification_code_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_code_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_code_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Existing accounts predate the email-verification flow — grandfather
    # them in so the next /login doesn't 403 them.
    op.execute("UPDATE users SET is_verified = TRUE")


def downgrade() -> None:
    op.drop_column("users", "password_reset_code_expires_at")
    op.drop_column("users", "password_reset_code_hash")
    op.drop_column("users", "verification_code_expires_at")
    op.drop_column("users", "verification_code_hash")
    op.drop_column("users", "is_verified")
