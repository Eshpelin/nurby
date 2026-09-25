"""record rule-level VLM usage estimates

Revision ID: f3c9e1a5b7d0
Revises: f3b8d0e2c4a6
Create Date: 2026-09-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f3c9e1a5b7d0"
down_revision: Union[str, None] = "f3b8d0e2c4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "perception_vlm_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("providers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_name", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("workload", sa.String(64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_perception_vlm_usage_camera_id", "perception_vlm_usage", ["camera_id"])
    op.create_index("ix_perception_vlm_usage_rule_id", "perception_vlm_usage", ["rule_id"])
    op.create_index("ix_perception_vlm_usage_event_id", "perception_vlm_usage", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_perception_vlm_usage_event_id", table_name="perception_vlm_usage")
    op.drop_index("ix_perception_vlm_usage_rule_id", table_name="perception_vlm_usage")
    op.drop_index("ix_perception_vlm_usage_camera_id", table_name="perception_vlm_usage")
    op.drop_table("perception_vlm_usage")
