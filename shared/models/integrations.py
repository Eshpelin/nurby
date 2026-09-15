"""Outbound integrations: Telegram channels and dialogs, the dedupe
ledger that keeps them from double-sending, and webhooks.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class TelegramChannel(Base):
    """User-owned Telegram bot channel for rule notifications.

    The bot token is stored Fernet-encrypted in ``bot_token_enc``. The
    target chat is established via the pairing flow. ``chat_id`` stays
    null until the user invokes ``/start <nonce>`` (DM) or
    ``/pair <nonce>`` (group) and the long-poller binds the chat. Once
    paired, the channel can be used as the target of a ``telegram``
    rule action.
    """

    __tablename__ = "telegram_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    bot_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_silent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Phase 3. delivery + rate limit + dedupe knobs.
    # delivery_mode is "long_poll" or "webhook". When "webhook" the
    # poller manager skips this channel and updates arrive via
    # POST /api/telegram/webhook/{channel_id}.
    delivery_mode: Mapped[str] = mapped_column(String(16), default="long_poll", nullable=False)
    # webhook_secret is a hex random shared secret. Telegram echoes it
    # in the X-Telegram-Bot-Api-Secret-Token header on every delivery
    # so we can reject forged updates. Functions like a per-channel
    # API key. never returned in API responses after creation.
    webhook_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Cached for display + setWebhook idempotency.
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # off | low (re-encode to 720p JPEG q70) | high (original bytes).
    media_quality: Mapped[str] = mapped_column(String(16), default="high", nullable=False)
    rate_limit_per_chat_qps: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    rate_limit_per_chat_burst: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    dedupe_window_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # Phase 4. Household sharing. When true, every user can pick this
    # channel in their rule builder + receive alerts on it. Ownership
    # (token, delete, edit token) stays with user_id. share_permissions
    # is 'use' (others can pick it) or 'use_and_test' (others can also
    # fire the test endpoint).
    shared_with_household: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    share_permissions: Mapped[str] = mapped_column(String(16), default="use", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TelegramOutboxDedupe(Base):
    """Short-lived ledger of outbound message hashes.

    Used by :class:`services.notify.telegram.DedupeStore` to suppress
    sending the same content to the same chat repeatedly within a
    user-configurable window. Rows older than an hour are pruned
    opportunistically on insert. an explicit retention worker is not
    needed because traffic naturally garbage-collects.
    """

    __tablename__ = "telegram_outbox_dedupe"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TelegramDialog(Base):
    """Multi-step in-chat state machine state.

    Phase 4. Drives face/body cluster naming over Telegram and the
    optional ask-yes-no prompt. One open dialog per (channel_id,
    chat_id, awaiting) is the contract enforced by the lookup index.
    ``context`` carries the kind-specific payload (cluster_id,
    event_id, etc.). ``expires_at`` is bumped on each user reply and
    a stale dialog is treated as terminal.
    """

    __tablename__ = "telegram_dialogs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_channels.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    awaiting: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── Agent v1 (Wave 1A) ──────────────────────────────────────────────
#
# Lifecycle + audit + cache tables for the agentic Q&A layer
# (docs/agent-design.md sections 5.4, 7, 11.1). Wave 1B (tool registry)
# writes AgentToolCall rows. Wave 1C (analyzer) writes AgentVlmCall +
# VlmFrameAnalysis. The driver in services/agent/runs.py owns row
# creation; see services/agent/budget.py for the daily-usage rollup.


class WebhookSubscription(Base):
    """Standing outbound webhook. Every fired Event is fanned out to all
    active subscriptions, in addition to per-rule webhook actions.

    Optional ``rule_ids`` / ``camera_ids`` JSON lists scope which events
    a subscription receives. ``secret`` enables HMAC body signing.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # JSON filter lists. NULL/empty means "all".
    rule_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    camera_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────
# Guardian by Nurby (docs/guardian-portal-product-brief.md section 24).
# A thin permission-and-view layer over the existing engine. These rows bind
# an existing User (role "guardian") to an existing Person, attach
# entitlements + alert prefs, register approved pickups, and log every view.
# No detection/identity/AI logic is forked here; presence, alerts, recaps,
# and search all delegate to existing Nurby subsystems.
# ─────────────────────────────────────────────────────────────────────────
