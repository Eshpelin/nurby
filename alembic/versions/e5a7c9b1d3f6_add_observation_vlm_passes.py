"""versioned VLM passes for idle enrichment

Revision ID: e5a7c9b1d3f6
Revises: d4f6a8c1e3b5
Create Date: 2026-06-06 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5a7c9b1d3f6'
down_revision: Union[str, None] = 'd4f6a8c1e3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("enrich_pass_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "observations",
        sa.Column("last_enriched_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "observation_vlm_passes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("observation_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pass_no", sa.Integer(), nullable=False),
        sa.Column("lens", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), server_default="v1", nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("authoritative", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("superseded", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("observation_id", "pass_no", name="ux_obs_pass_no"),
    )
    op.create_index("ix_obs_passes_observation_id", "observation_vlm_passes", ["observation_id"])

    # Backfill. every existing live caption becomes pass 1, authoritative,
    # so the pass history starts complete and reversible.
    op.execute(
        """
        INSERT INTO observation_vlm_passes
            (id, observation_id, pass_no, lens, prompt_version, provider_name,
             model, description, authoritative, superseded, created_at)
        SELECT gen_random_uuid(), id, 1, 'live', 'v1', vlm_provider,
               NULL, vlm_description, true, false, COALESCE(started_at, now())
        FROM observations
        WHERE vlm_description IS NOT NULL
        """
    )
    op.execute(
        "UPDATE observations SET enrich_pass_count = 1 WHERE vlm_description IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_obs_passes_observation_id", table_name="observation_vlm_passes")
    op.drop_table("observation_vlm_passes")
    op.drop_column("observations", "last_enriched_at")
    op.drop_column("observations", "enrich_pass_count")
