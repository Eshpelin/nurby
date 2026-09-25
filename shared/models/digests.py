"""Things Nurby writes rather than observes: digests, notifications,
scheduled reports, dashboard widgets and remembered household facts.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class DigestEntry(Base):
    __tablename__ = "digest_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    highlights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_observations: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyDigest(Base):
    """Household-wide morning summary. One row per generation run.

    Aggregates the last 24h across observations, incidents,
    journeys, audio detections, and conversations. Free-form
    summary_text plus a structured ``facts`` dict so the UI can
    render bullet lists without re-parsing the LLM output.
    """

    __tablename__ = "daily_digests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Per-guardian inbox. Null = household/operator-wide notification (the
    # original behaviour); set = a private copy for one guardian user.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When this alert was actually handed to a delivery path (push mirror,
    # Telegram, email). Null means persisted-only, never delivered. Used by
    # verified-activation (#193) to prove a real delivery, not just a write.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduledReport(Base):
    """A saved, recurring agent question with a delivery schedule.

    Distinct from the morning digest: the digest is one fixed household
    recap; a scheduled report is any question, optionally scoped to one
    person, on its own clock. "What was Simon doing all day, every night
    at 7 PM" is one row here. The runner (services/api/report_scheduler)
    feeds the prompt through the same agent pipeline as Ask Nurby and
    delivers the grounded answer to the configured channels.
    """

    __tablename__ = "scheduled_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional person focus. The runner injects the person's name into the
    # agent question so identity resolution starts grounded.
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True
    )
    # Local time-of-day in the household timezone (system_timezone setting).
    hour: Mapped[int] = mapped_column(Integer, default=19)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    # Days like ["mon","tue"]. Null = every day.
    days: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Delivery channels: {"notify": bool, "email": str|null}. Telegram later.
    delivery: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Budgets and run attribution use the creator's identity.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DashboardWidget(Base):
    """A user-defined dashboard tile that pulls data from an external HTTP
    API and renders it, either via a built-in template (mapping fields onto
    Nurby components) or sandboxed custom HTML/JS. The auth secret is sealed
    at rest (shared.camera_secrets); the backend proxies the fetch so the key
    never reaches the browser. Positioned in the camera wall like any tile.
    """

    __tablename__ = "dashboard_widgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # "template" | "custom"
    render_kind: Mapped[str] = mapped_column(String(16), default="template", nullable=False)
    # {method, url, query?, headers?, body?, auth_kind, auth_name?, refresh_seconds}
    source: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Sealed (Fernet) API key/token. Never returned to the client.
    auth_secret: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # {type, bindings, options} for render_kind == "template"
    template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Sandboxed source for render_kind == "custom"
    custom_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Default span hint {w, h}; per-browser position lives in the wall's localStorage.
    layout: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HouseholdFact(Base):
    """A durable, distilled fact about how this household usually works.

    The orientation block is built fresh from live state on every run, so
    it can only state what a query returns right now. It cannot hold
    something like "the cat is usually on the Back Door camera between
    2am and 5am", which is exactly the kind of knowledge that prevents a
    whole class of wrong answer (issue #141).

    Curator invariants, shared with EntityAssociation and enforced in
    ``services.agent.curator``:

    - Only ``source="agent"`` rows are ever auto-modified. A fact a person
      wrote is theirs, and the curator does not touch it.
    - Nothing is auto-deleted. A fact that stops matching is archived, and
      archive is recoverable.
    - ``pinned`` bypasses every automatic transition.
    - ``rejected`` is permanent. A rejected fact is never proposed again,
      which is the difference between a system that learns and one that
      nags.

    Issue #185 adds the capture/review/use loop on top: what the fact is
    about (``entity_kind``/``entity_key``), an optional recurring schedule,
    explicit alert suppression (armed only by a person, never by the
    curator), who wrote and last edited the row, and the evidence the
    belief rests on.
    """

    __tablename__ = "household_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The fact itself, one sentence, in plain language.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # A stable key for the thing the fact is about, so a re-derived fact
    # updates its row instead of creating a near-duplicate.
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the fact is attached to: household | person | vehicle | camera.
    # entity_key is that entity's stable key (UUID as string); "household"
    # means the whole home. Null on rows from before #185.
    entity_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    entity_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="habit")
    # agent (distilled) | user (written by a person)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    # candidate | established | archived | rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Optional recurrence: weekdays as ints (0=Monday, matching
    # datetime.weekday()), a local-time window in minutes since midnight,
    # and the IANA zone the window lives in (None = household zone).
    schedule_days: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schedule_start_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_end_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_tz: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Alert suppression is armed by a person, explicitly, after the fact is
    # established; a learned habit never mutes anything on its own. Hits are
    # counted so the household can see what the note silenced.
    suppresses_alerts: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suppression_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suppression_confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    suppression_hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_suppressed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Provenance: who wrote it, who last edited it, and through which
    # surface (web | api | agent_chat | curator).
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_via: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Lifecycle transition timestamps beyond archive/re-confirm above.
    established_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Why Nurby believes this: references into association/event/observation
    # rows, written by the curator. A user note needs no evidence.
    evidence_refs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set when the curator last saw evidence for this fact. Staleness is
    # measured from here, never from created_at.
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("subject_key", "kind", "source", name="uq_household_fact"),
        # Suppression checks run on the rule-engine tick; keep that lookup
        # to the small armed subset.
        Index("ix_household_facts_suppression", "suppresses_alerts", "status"),
    )
