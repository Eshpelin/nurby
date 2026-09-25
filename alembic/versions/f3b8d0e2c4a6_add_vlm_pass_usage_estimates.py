"""store estimated usage for camera VLM passes

Revision ID: f3b8d0e2c4a6
Revises: f3a7c9e1b5d2
Create Date: 2026-09-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3b8d0e2c4a6"
down_revision: Union[str, None] = "f3a7c9e1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "observation_vlm_passes",
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "observation_vlm_passes",
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "observation_vlm_passes",
        sa.Column("cost_cents", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("observation_vlm_passes", "cost_cents")
    op.drop_column("observation_vlm_passes", "tokens_out")
    op.drop_column("observation_vlm_passes", "tokens_in")
