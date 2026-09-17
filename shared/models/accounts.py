"""People who can sign in, what they are allowed to reach, the devices
they get pushed to, and the AI providers and settings they configure.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("camera_access_mode IN ('all', 'selected', 'none')", name="ck_users_camera_access_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # admin, viewer, guardian
    camera_access_mode: Mapped[str] = mapped_column(String(16), default="none", server_default="none", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Auto-created first-run owner that has not set real credentials yet.
    # The app drops a new user straight in via /auth/bootstrap, then nags
    # them to claim the account (set email + password) which clears this.
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The invite key this user redeemed to create their account, if any. Lets
    # an admin see who each key brought in and when (the redeemed_at is this
    # user's created_at). SET NULL on key delete so revoking a key never
    # removes the accounts it created; the audit link just drops.
    invite_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invite_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )


class InviteKey(Base):
    __tablename__ = "invite_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # role assigned to users who redeem this key
    camera_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # list of camera UUIDs to grant on redeem
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceShare(Base):
    """An anonymous, scoped, revocable share link for ONE recorded resource.

    A recipient opens ``/share/<token>`` with no account and sees only the
    shared thing (a clip, a frame, an event, or a read-only feed of one
    camera's past events) — never anything else, never live. The raw token is
    shown to the creator once and never stored; we keep only its SHA-256 hash,
    so a database leak does not expose live share URLs (same posture as an API
    key). Access ends the instant ``revoked_at`` is set, once ``expires_at``
    passes, or once ``view_count`` reaches ``max_views`` (null = unlimited).

    Media is served by reusing the normal recording/observation/event paths, so
    a share inherits the system's selective privacy blur automatically — it
    shows exactly what a restricted viewer would see, not a blanket blur.

    Exactly one of the ``*_id`` columns is set, matching ``kind``; enforced in
    the create route rather than by a DB constraint.
    """

    __tablename__ = "resource_shares"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # SHA-256 hex of the raw url-safe token. Lookups hash the presented token
    # and match on this; the raw token lives only in the shared URL.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # recording|observation|event|camera_events

    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recordings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True, index=True
    )

    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Who created it (audit). SET NULL so removing a user doesn't silently
    # delete the shares they handed out; the row stays revocable/auditable.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # View cap. null = unlimited; a view is counted once per page/metadata
    # resolve, NOT per media byte-range request (a single watch must not burn
    # the whole allowance).
    max_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserCameraAccess(Base):
    __tablename__ = "user_camera_access"
    __table_args__ = (UniqueConstraint("user_id", "camera_id", name="uq_user_camera"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushDevice(Base):
    __tablename__ = "push_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)  # ios, android
    # FCM registration token. Unique so re-registering the same physical
    # device (new login, reinstalled app) re-assigns the existing row to
    # the current user instead of duplicating it.
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Bumped on every re-register so stale rows are visible to future
    # housekeeping (FCM invalidates truly dead tokens on send anyway).
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApiKey(Base):
    """Long-lived machine credential for programmatic API access.

    The plaintext key (``nrb_<random>``) is shown once at creation and
    never stored. We persist a sha256 hash for constant-time lookup and
    a short prefix for display. Keys are scoped (read / write) and can
    carry an optional expiry; revocation stamps ``revoked_at``.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # sha256 hex of the full plaintext key. Indexed for O(1) auth lookup.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # First chars of the key (e.g. "nrb_ab12cd") for UI display only.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    # Advisory scope. "read" or "write". write implies read.
    scope: Mapped[str] = mapped_column(String(16), default="read", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Token caps. NULL = no cap, defer to the provider's model default.
    # Per-camera vlm_max_tokens / summary_max_tokens further tighten
    # the output cap when set.
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ── Optional reasoning / "thinking" model controls (issue #41) ──────
    # All NULL by default so behavior is unchanged unless an admin opts
    # in. These are read by services.perception.vlm and services.agent.llm
    # via shared.reasoning.resolve_reasoning_params; see that module for
    # the per-provider wire shape.
    #
    # anthropic_thinking: one of "adaptive" | "enabled" | "off" (or NULL,
    #   treated as off). "adaptive" lets Claude decide depth (Opus 4.6+);
    #   "enabled" uses a fixed budget (older models, needs
    #   anthropic_thinking_budget_tokens < max_output_tokens).
    anthropic_thinking: Mapped[str | None] = mapped_column(String(16), nullable=True)
    anthropic_thinking_budget_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # openai_reasoning_effort: one of "minimal" | "low" | "medium" | "high"
    #   (or NULL = off). Sent as reasoning_effort to OpenAI reasoning models
    #   (o-series / gpt-5-class). Ignored by non-reasoning chat models.
    openai_reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HouseholdModeChange(Base):
    """One row every time the household mode changes (#184).

    The current mode lives in app settings, because that is what the rule
    engine reads once per tick. This table is the history: it is what the
    timeline shows and what "why didn't I get an alert at 3pm" needs.
    """

    __tablename__ = "household_mode_changes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # manual | agent | auto. See shared/household_mode.py.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Free text a person can leave ("off to the airport"), or the reason
    # the agent gives. Shown on the timeline entry.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
