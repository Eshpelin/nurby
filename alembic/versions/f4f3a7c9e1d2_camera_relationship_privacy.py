"""Add per-camera relationship inference privacy controls (#256)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4f3a7c9e1d2"
down_revision: Union[str, None] = "f4e2a6c8b0d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("relationship_inference_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("cameras", sa.Column("relationship_notifications_enabled", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    op.drop_column("cameras", "relationship_notifications_enabled")
    op.drop_column("cameras", "relationship_inference_enabled")
