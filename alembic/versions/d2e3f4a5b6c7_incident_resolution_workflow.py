"""Incident resolution + ownership workflow (#197).

'Seen' and 'resolved' are different outcomes. This adds lightweight
resolved / dismissed states to incidents, plus who handled one and when, an
optional assignee for business pilots, and a free-text resolution reason, so
a household or team can inspect and close an incident without hunting across
pages and shared users can see who handled it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # open (default) | resolved | dismissed. Server default so existing rows
    # read as open rather than NULL.
    op.add_column(
        "incidents",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
    )
    op.add_column("incidents", sa.Column("resolution_reason", sa.String(length=255), nullable=True))
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "incidents",
        sa.Column(
            "resolved_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "assigned_to_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Triage list filters by status, most often "open".
    op.create_index("ix_incidents_status", "incidents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_column("incidents", "assigned_to_user_id")
    op.drop_column("incidents", "resolved_by_user_id")
    op.drop_column("incidents", "resolved_at")
    op.drop_column("incidents", "resolution_reason")
    op.drop_column("incidents", "status")
