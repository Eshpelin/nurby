"""telegram phase 4. household sharing + event notes + dialog state + cluster naming prompts

Revision ID. b1c2d3e4f5a8
Revises. a1b2c3d4e5f7

Phase 4 of the Telegram notification pipeline adds.

* ``telegram_channels.shared_with_household`` + ``share_permissions``
  so a household member can opt a channel into shared use by every
  user. Token + chat binding remain owner-only. Sharing is read-mostly.
* ``event_notes`` table for free-text annotations on events. Source is
  one of ``telegram | web | api``. Replying to a Telegram alert
  message lands here.
* ``telegram_dialogs`` table for multi-step in-chat state machines
  (face/body cluster naming, ask-yes-no prompts, future workflows).
  Lookup-on-message is keyed by (channel_id, chat_id, awaiting).
* ``face_clusters.naming_prompted_at`` +
  ``body_clusters.naming_prompted_at`` so the system never re-prompts
  the same cluster.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b1c2d3e4f5a8"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── telegram_channels household sharing ─────────────────────────
    op.add_column(
        "telegram_channels",
        sa.Column(
            "shared_with_household",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "telegram_channels",
        sa.Column(
            "share_permissions",
            sa.String(length=16),
            nullable=False,
            server_default="use",
        ),
    )

    # ── event_notes table ───────────────────────────────────────────
    op.create_table(
        "event_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_event_notes_event_id_created_at",
        "event_notes",
        ["event_id", "created_at"],
    )

    # ── telegram_dialogs table ──────────────────────────────────────
    op.create_table(
        "telegram_dialogs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telegram_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("awaiting", sa.String(length=32), nullable=True),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_telegram_dialogs_lookup",
        "telegram_dialogs",
        ["channel_id", "chat_id", "awaiting"],
    )

    # ── face/body cluster naming prompt timestamps ──────────────────
    op.add_column(
        "face_clusters",
        sa.Column(
            "naming_prompted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "body_clusters",
        sa.Column(
            "naming_prompted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("body_clusters", "naming_prompted_at")
    op.drop_column("face_clusters", "naming_prompted_at")
    op.drop_index("ix_telegram_dialogs_lookup", table_name="telegram_dialogs")
    op.drop_table("telegram_dialogs")
    op.drop_index("ix_event_notes_event_id_created_at", table_name="event_notes")
    op.drop_table("event_notes")
    op.drop_column("telegram_channels", "share_permissions")
    op.drop_column("telegram_channels", "shared_with_household")
