"""Add the opt-in VLM scene-baseline content-health toggle (#212)."""

import sqlalchemy as sa

from alembic import op

revision = "f8a2b4c6d8e0"
down_revision = "f7a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "scene_baseline_detection_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "scene_baseline_detection_enabled")
