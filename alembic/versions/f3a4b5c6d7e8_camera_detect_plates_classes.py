"""per-camera detect_plates toggle + detect_classes override

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-06-16 00:00:00.000000

Adds a per-camera license-plate toggle (basic, on by default) and a
per-camera object-class allowlist override (null = inherit the global
detect_classes setting).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("detect_plates", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("cameras", sa.Column("detect_classes", JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "detect_classes")
    op.drop_column("cameras", "detect_plates")
