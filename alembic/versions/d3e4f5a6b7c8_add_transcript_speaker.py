"""add speaker attribution columns to transcripts

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-25 09:00:00.000000

Phase 2 of audio plan, Tier A speaker attribution. Three columns on
``transcripts``. ``speaker_person_id`` references ``persons``.
``speaker_source`` is one of ``video`` | ``ambiguous`` | ``fused`` |
``voice``. ``speaker_confidence`` is the underlying signal's score
(coverage for video, cosine for voice).

Phase 3 introduces voice samples and may add columns again. We keep
this migration minimal so it does not bake a forward decision.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transcripts",
        sa.Column(
            "speaker_person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "transcripts",
        sa.Column("speaker_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "transcripts",
        sa.Column("speaker_source", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcripts", "speaker_source")
    op.drop_column("transcripts", "speaker_confidence")
    op.drop_column("transcripts", "speaker_person_id")
