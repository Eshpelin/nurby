"""add devices table + agent_runs.mentions (@ mentions / device registry)

Revision ID: a4c8e2d6f0b3
Revises: f1a3c5e7b9d2
Create Date: 2026-07-04 00:00:00.000000

Devices become first-class rows so rules can reference a device_id that
resolves endpoint/secret/payload at fire time (rename-safe, secret stored
once, sealed). agent_runs.mentions persists the @-mentions attached to a
question so multi-turn follow-ups keep the pre-resolved entity ids.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4c8e2d6f0b3"
down_revision: Union[str, None] = "f1a3c5e7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("preset_id", sa.String(length=64), nullable=True),
        sa.Column("endpoint_url", sa.String(length=1024), nullable=False),
        sa.Column("secret", sa.String(length=2048), nullable=True),
        sa.Column("payload_template", sa.JSON(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), server_default="5", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("agent_runs", sa.Column("mentions", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "mentions")
    op.drop_table("devices")
