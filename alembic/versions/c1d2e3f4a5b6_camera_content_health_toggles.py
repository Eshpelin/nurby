"""Per-camera content-health toggles (#212).

Adds independently-toggleable content-health switches to ``cameras`` so a
frozen/obscured/tampered-view check can be turned on per camera, which the
issue's acceptance criteria require. A master switch plus one flag per
detection path. Existing rows default to the safe posture: the feature off,
but each path pre-armed so enabling the master is enough.
"""

import sqlalchemy as sa

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "80c9c11f3e1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Master switch, off by default so the feature ships dark and is opted
    # into per camera (or globally via the content_health_enabled app setting).
    op.add_column(
        "cameras",
        sa.Column("content_health_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Individual detection paths, armed by default so flipping the master on
    # gets both checks without extra clicks. Toggle either off per camera.
    op.add_column(
        "cameras",
        sa.Column("freeze_detection_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "cameras",
        sa.Column("obscuration_detection_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("cameras", "obscuration_detection_enabled")
    op.drop_column("cameras", "freeze_detection_enabled")
    op.drop_column("cameras", "content_health_enabled")
