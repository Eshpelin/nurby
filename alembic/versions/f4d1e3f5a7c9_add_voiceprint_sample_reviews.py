"""Store explicit decisions for existing-audio voiceprint candidates (#272)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f4d1e3f5a7c9"
down_revision: Union[str, None] = "f4c0d2e4a6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voiceprint_sample_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("consent_given", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("person_id", "transcript_id", name="uq_voiceprint_sample_review"),
    )
    op.create_index("ix_voiceprint_sample_reviews_person_id", "voiceprint_sample_reviews", ["person_id"])
    op.create_index("ix_voiceprint_sample_reviews_transcript_id", "voiceprint_sample_reviews", ["transcript_id"])
    op.create_index("ix_voiceprint_sample_reviews_reviewed_by_user_id", "voiceprint_sample_reviews", ["reviewed_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_voiceprint_sample_reviews_reviewed_by_user_id", table_name="voiceprint_sample_reviews")
    op.drop_index("ix_voiceprint_sample_reviews_transcript_id", table_name="voiceprint_sample_reviews")
    op.drop_index("ix_voiceprint_sample_reviews_person_id", table_name="voiceprint_sample_reviews")
    op.drop_table("voiceprint_sample_reviews")
