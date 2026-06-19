"""add grounding_results (FindAnything visual-grounding cache + tags)

Revision ID: d8b2f4a6c0e3
Revises: c2e4f6a8b0d1
Create Date: 2026-06-19 00:00:00.000000

Append-only store of FindAnything grounding results, one row per
(observation_id, prompt_hash, model_revision). It serves two jobs at once
(docs/findanything-design.md §7): a persistent idempotency cache so a
retrospective scan never re-runs the GPU on the same frame+prompt, and the
teach-the-index tag store so the next search for a located term is instant.
Safe-by-default w.r.t. rules. the engine only evaluates live rule_data and
never re-runs against these stored rows (§7.1). The unique constraint is the
upsert/lookup key; the prompt_hash index serves the cache probe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8b2f4a6c0e3"
down_revision: Union[str, None] = "c2e4f6a8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "grounding_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("observation_id", sa.UUID(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("model_revision", sa.String(length=64), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("corroborated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boxes", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["observation_id"], ["observations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id", "prompt_hash", "model_revision",
            name="ux_grounding_obs_prompt_rev",
        ),
    )
    op.create_index(
        "ix_grounding_results_observation_id",
        "grounding_results",
        ["observation_id"],
        unique=False,
    )
    op.create_index(
        "ix_grounding_results_prompt_hash",
        "grounding_results",
        ["prompt_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_grounding_results_prompt_hash", table_name="grounding_results")
    op.drop_index("ix_grounding_results_observation_id", table_name="grounding_results")
    op.drop_table("grounding_results")
