"""add person nickname

Household-wide colloquial display name. Nullable. View-layer only.

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-05-26 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persons",
        sa.Column("nickname", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persons", "nickname")
