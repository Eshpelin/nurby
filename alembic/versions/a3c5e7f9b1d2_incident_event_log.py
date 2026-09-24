"""Append-only incident event log for ownership/audit (#197).

"Shared users see who handled an incident and when" is only durable if the
history survives a reopen. The single ``resolved_by`` column on ``incidents``
is overwritten (and cleared on reopen), so this adds an append-only log of
every workflow transition: resolved, dismissed, reopened, assigned,
unassigned, with the actor, an optional reason, and the time.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "a3c5e7f9b1d2"
down_revision = "f8a2b4c6d8e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "actor_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_incident_events_incident_created",
        "incident_events",
        ["incident_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_incident_events_incident_created", table_name="incident_events")
    op.drop_table("incident_events")
