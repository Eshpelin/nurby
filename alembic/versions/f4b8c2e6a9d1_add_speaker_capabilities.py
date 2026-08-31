"""probed camera speaker capability

Revision ID: f4b8c2e6a9d1
Revises: e1a7c4b9d6f2
Create Date: 2026-08-29 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f4b8c2e6a9d1'
down_revision: Union[str, None] = 'e1a7c4b9d6f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "speaker_capabilities",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "camera_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("transport", sa.String(32), nullable=False, server_default="none"),
        sa.Column("supported", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("codec", sa.String(16), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("endpoint", sa.String(1024), nullable=True),
        sa.Column("vendor", sa.String(64), nullable=True),
        sa.Column(
            "probed_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("probe_error", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_speaker_capabilities_camera_id", "speaker_capabilities", ["camera_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_speaker_capabilities_camera_id", table_name="speaker_capabilities"
    )
    op.drop_table("speaker_capabilities")
