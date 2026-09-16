"""Explicit camera access; preserve existing scope and deny new accounts (#190)."""

import sqlalchemy as sa
from alembic import op

revision = "f9c2d4e6a8b0"
down_revision = "e4a7c2d9b1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("camera_access_mode", sa.String(16), nullable=False, server_default="none"))
    # Snapshot the old policy once. A selected user's last grant can then be
    # removed without accidentally restoring unrestricted access.
    op.execute("""
        UPDATE users SET camera_access_mode = CASE
            WHEN role = 'admin' THEN 'all'
            WHEN EXISTS (SELECT 1 FROM user_camera_access a WHERE a.user_id = users.id)
                THEN 'selected'
            ELSE 'all'
        END
    """)
    op.create_check_constraint(
        "ck_users_camera_access_mode", "users", "camera_access_mode IN ('all', 'selected', 'none')"
    )


def downgrade() -> None:
    # The old policy cannot represent zero access: removing this field would
    # silently grant every camera to denied accounts. Refuse that downgrade.
    raise RuntimeError("Camera access cannot be safely downgraded to the zero-grants-means-all policy")
