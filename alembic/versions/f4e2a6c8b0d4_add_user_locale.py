"""Persist each user's presentation locale (#265)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4e2a6c8b0d4"
down_revision: Union[str, None] = "f4d1e3f5a7c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(16), server_default="en", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "locale")
