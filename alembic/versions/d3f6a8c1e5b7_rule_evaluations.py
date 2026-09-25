"""Store decisive rule evaluation reasons (#287)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "d3f6a8c1e5b7"
down_revision = "c1e4a7b9d2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_evaluations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", UUID(as_uuid=True), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("camera_id", UUID(as_uuid=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("details", JSON, nullable=True),
    )
    op.create_index("ix_rule_evaluations_rule_id", "rule_evaluations", ["rule_id"])
    op.create_index("ix_rule_evaluations_observation_id", "rule_evaluations", ["observation_id"])
    op.create_index("ix_rule_evaluations_camera_id", "rule_evaluations", ["camera_id"])
    op.create_index("ix_rule_evaluations_evaluated_at", "rule_evaluations", ["evaluated_at"])


def downgrade() -> None:
    op.drop_table("rule_evaluations")
