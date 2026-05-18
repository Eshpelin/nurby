"""telegram webhook delivery, rate limits, dedupe

Revision ID. a1b2c3d4e5f7
Revises. e2a3b4c5d7e8

Phase 3 of the Telegram notification pipeline. Adds.

* Per-channel delivery mode (long_poll or webhook).
* Webhook secret + cached webhook URL for setWebhook idempotency.
* Media quality preference (off / low / high) controlling re-encode
  before Telegram upload.
* Per-chat token bucket rate-limit knobs.
* Dedupe window (seconds) for suppressing identical messages within a
  short window.

Adds a small ``telegram_outbox_dedupe`` table used by the dedupe store.
Hashes are short (sha256 hex) so the table stays tiny. The DedupeStore
also prunes rows older than an hour opportunistically.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "e2a3b4c5d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_channels",
        sa.Column(
            "delivery_mode",
            sa.String(length=16),
            nullable=False,
            server_default="long_poll",
        ),
    )
    op.add_column(
        "telegram_channels",
        sa.Column("webhook_secret", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "telegram_channels",
        sa.Column("webhook_url", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "telegram_channels",
        sa.Column(
            "media_quality",
            sa.String(length=16),
            nullable=False,
            server_default="high",
        ),
    )
    op.add_column(
        "telegram_channels",
        sa.Column(
            "rate_limit_per_chat_qps",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
    )
    op.add_column(
        "telegram_channels",
        sa.Column(
            "rate_limit_per_chat_burst",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )
    op.add_column(
        "telegram_channels",
        sa.Column(
            "dedupe_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )

    op.create_table(
        "telegram_outbox_dedupe",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telegram_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_telegram_outbox_dedupe_lookup",
        "telegram_outbox_dedupe",
        ["channel_id", "hash", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_outbox_dedupe_lookup", table_name="telegram_outbox_dedupe")
    op.drop_table("telegram_outbox_dedupe")
    op.drop_column("telegram_channels", "dedupe_window_seconds")
    op.drop_column("telegram_channels", "rate_limit_per_chat_burst")
    op.drop_column("telegram_channels", "rate_limit_per_chat_qps")
    op.drop_column("telegram_channels", "media_quality")
    op.drop_column("telegram_channels", "webhook_url")
    op.drop_column("telegram_channels", "webhook_secret")
    op.drop_column("telegram_channels", "delivery_mode")
