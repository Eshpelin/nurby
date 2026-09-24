"""Add source-level evidence episodes for identity associations (#253)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "d0e1f2a3b4c5"
down_revision = "c7e9a1b3d5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "association_evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "association_id", UUID(as_uuid=True),
            sa.ForeignKey("entity_associations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("episode_key", sa.String(length=255), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="supporting"),
        sa.Column(
            "journey_id", UUID(as_uuid=True),
            sa.ForeignKey("journeys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("observation_ids", JSON(), nullable=True),
        sa.Column("camera_ids", JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("metadata", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("association_id", "episode_key", name="uq_association_evidence_episode"),
    )
    op.create_index("ix_association_evidence_association_id", "association_evidence", ["association_id"])
    op.create_index("ix_association_evidence_journey_id", "association_evidence", ["journey_id"])
    op.create_index("ix_association_evidence_observed_at", "association_evidence", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_association_evidence_observed_at", table_name="association_evidence")
    op.drop_index("ix_association_evidence_journey_id", table_name="association_evidence")
    op.drop_index("ix_association_evidence_association_id", table_name="association_evidence")
    op.drop_table("association_evidence")
