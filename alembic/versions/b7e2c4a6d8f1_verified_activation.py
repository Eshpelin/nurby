"""Verified first-useful-result tracking (#193 / #204 phase 2).

Adds the per-user activation milestone table and a delivery timestamp on
notifications so a real, delivered alert can be distinguished from a
persisted-only one.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b7e2c4a6d8f1"
down_revision = "a8d1f3b5c7e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "activation_milestones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal", sa.String(length=32), nullable=False),
        sa.Column("camera_id", UUID(as_uuid=True), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rule_id", UUID(as_uuid=True), sa.ForeignKey("rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("draft_rule_id", UUID(as_uuid=True), sa.ForeignKey("rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("configured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_useful_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_kind", sa.String(length=16), nullable=True),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("delivery_ok", sa.Boolean(), nullable=True),
        sa.Column("install_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "goal", name="uq_activation_user_goal"),
    )
    op.create_index("ix_activation_milestones_user_id", "activation_milestones", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_activation_milestones_user_id", table_name="activation_milestones")
    op.drop_table("activation_milestones")
    op.drop_column("notifications", "delivered_at")
