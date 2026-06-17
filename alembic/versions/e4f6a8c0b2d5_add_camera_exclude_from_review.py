"""add cameras.exclude_from_review flag

Revision ID: e4f6a8c0b2d5
Revises: d9e0f1a2b3c4, f3a4b5c6d7e8
Create Date: 2026-06-17 00:00:00.000000

Per-camera review visibility. When true the camera is hidden from the
review / alerts / timeline feed and their filters, but keeps recording
and stays a valid recording target. Distinct from the dashboard camera-
wall hide, which is a per-browser layout choice with no server state.

Also merges the two open migration heads (the vlm_late flag and the
detect-class/plate-gating branch) so the tree has a single head again.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e4f6a8c0b2d5"
down_revision: Union[str, Sequence[str], None] = ("d9e0f1a2b3c4", "f3a4b5c6d7e8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "exclude_from_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "exclude_from_review")
