"""Store consent-gated local voiceprint profiles (#272)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "fe5f7b9c1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voiceprint_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding", Vector(240), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=False, server_default="mfcc-local-v1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="not_ready"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_transcript_ids", postgresql.JSON(), nullable=True),
        sa.Column("consent_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("person_id", name="uq_voiceprint_profile_person"),
    )
    op.create_index("ix_voiceprint_profiles_person_id", "voiceprint_profiles", ["person_id"])


def downgrade() -> None:
    op.drop_index("ix_voiceprint_profiles_person_id", table_name="voiceprint_profiles")
    op.drop_table("voiceprint_profiles")
