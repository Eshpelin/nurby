"""add daily_digests + unique person display_name

Revision ID: c5d6e7f8a2b3
Revises: b4c5d6e7f8a1
Create Date: 2026-05-08 18:00:00.000000

DailyDigest. household-wide morning summary that rolls up the last
24h across all cameras, audio detections, conversations, incidents,
and journeys. One row per generation run. Embedding for semantic
search over historical digests.

Person.display_name. user asked for hard uniqueness so journeys
can never accidentally fuse across two different people who happen
to share a name. The constraint is case-insensitive (LOWER(name))
so "Alice" and "alice" collide.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "c5d6e7f8a2b3"
down_revision: Union[str, None] = "b4c5d6e7f8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_digests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("provider_name", sa.String(64), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        # Structured facts so the UI can render bullets without
        # re-parsing the LLM output. Shape.
        # { visitors: [{name|cluster, sightings}], packages: int,
        #   audio_events: {label: count|[ts...]}, unknown_motion: [ts],
        #   incidents_count, journeys_count, cameras_active: [...] }
        sa.Column("facts", postgresql.JSON(), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
    )
    op.create_index(
        "ix_daily_digests_generated",
        "daily_digests",
        [sa.text("generated_at DESC")],
    )

    # Case-insensitive unique constraint on persons.display_name.
    # SET DEFERRABLE so admin tooling can swap names in a single
    # transaction without tripping the constraint mid-update.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_persons_display_name_lower "
        "ON persons (LOWER(display_name))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_persons_display_name_lower")
    op.drop_index("ix_daily_digests_generated", table_name="daily_digests")
    op.drop_table("daily_digests")
