"""Record exact prompt identity and text on VLM passes (#218)."""

import sqlalchemy as sa

from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "observation_vlm_passes",
        sa.Column("prompt_key", sa.String(length=64), nullable=False, server_default="legacy/unknown"),
    )
    op.add_column("observation_vlm_passes", sa.Column("prompt_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("observation_vlm_passes", "prompt_text")
    op.drop_column("observation_vlm_passes", "prompt_key")
