"""add conversations.cleaned_text

Revision ID: a6b7c8d9e1f2
Revises: f5a6b7c8d9e1
Create Date: 2026-05-07 15:30:00.000000

Stores a polished version of the conversation transcript with
filler removed, punctuation normalized, and capitalization fixed.
The raw per-segment transcripts stay untouched on the transcripts
table so the audit trail is preserved. The cleaned version is what
the dashboard card shows when the user expands a finalized
conversation and toggles to the cleaned view.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a6b7c8d9e1f2"
down_revision: Union[str, None] = "f5a6b7c8d9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("cleaned_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "cleaned_text")
