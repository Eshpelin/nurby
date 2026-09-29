"""Track direct email and Telegram rule-action deliveries (#199)."""

import sqlalchemy as sa
from alembic import op


revision = "ff9d1e3f5a7b"
# Merge the pre-existing voiceprint branch with the retained-monitoring
# branch before adding this ledger; the repository must retain one upgrade
# head for fresh installs.
down_revision = ("f0a1b2c3d4e5", "ff8c0d2e4f6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_channel_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=True),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id", "rule_id", "channel", "destination",
            name="uq_event_channel_delivery_destination",
        ),
    )
    op.create_index("ix_event_channel_deliveries_event_id", "event_channel_deliveries", ["event_id"])
    op.create_index("ix_event_channel_deliveries_rule_id", "event_channel_deliveries", ["rule_id"])


def downgrade() -> None:
    op.drop_index("ix_event_channel_deliveries_rule_id", table_name="event_channel_deliveries")
    op.drop_index("ix_event_channel_deliveries_event_id", table_name="event_channel_deliveries")
    op.drop_table("event_channel_deliveries")
