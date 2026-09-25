"""Prompt provenance on live captions and action labels (#218).

Existing rows are stamped legacy/unknown rather than guessed: action rows via
the column default, observations by leaving the new columns NULL.
"""

import sqlalchemy as sa

from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("observations", sa.Column("caption_prompt_key", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("caption_prompt_version", sa.String(length=24), nullable=True))
    op.add_column("observations", sa.Column("caption_prompt_text", sa.Text(), nullable=True))
    op.add_column(
        "observation_actions",
        sa.Column("prompt_key", sa.String(length=64), nullable=False, server_default="legacy/unknown"),
    )
    op.add_column(
        "observation_actions",
        sa.Column("prompt_version", sa.String(length=24), nullable=False, server_default="legacy"),
    )


def downgrade() -> None:
    op.drop_column("observation_actions", "prompt_version")
    op.drop_column("observation_actions", "prompt_key")
    op.drop_column("observations", "caption_prompt_text")
    op.drop_column("observations", "caption_prompt_version")
    op.drop_column("observations", "caption_prompt_key")
