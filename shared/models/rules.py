"""Rules the household wrote, the sequence instances tracking a
multi-step rule mid-flight, and the events rules fire.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger_pattern: Mapped[dict] = mapped_column(JSON, nullable=False)
    conditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actions: Mapped[dict] = mapped_column(JSON, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300)
    # Rule-level snooze. Set by the "Snooze rule 1h" Telegram button.
    # While now() < snoozed_until, the telegram action skips all sends
    # for this rule regardless of event/camera. Cleared by ops or by
    # the user from the rule builder. Mute and snooze are deliberately
    # separate. snooze is rule-wide, mute is per-event. Snooze wins.
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Triage taxonomy. "alert" rules are the front-page, push-worthy tier;
    # "detection" rules are record-keeping that stays behind a tab. A
    # verify action with on_fail="demote" can downgrade a single event
    # from alert to detection at fire time.
    severity: Mapped[str] = mapped_column(String(16), default="alert")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleSequenceInstance(Base):
    """An in-flight temporal sequence rule (docs/sequence-rules-design.md).

    A sequence rule = a normal trigger (step 0 / start) + a `sequence` block in
    its trigger_pattern holding ordered steps (each a check + time window). When
    the start trigger fires we create an instance here; subsequent observations
    that satisfy the current step within its deadline advance it; the last step
    completing runs the rule's on_complete actions, and a step lapsing past its
    deadline marks the instance expired (the sweeper handles that, and fires
    on_timeout in a later slice).

    `correlation_key` binds steps to the same subject/scope (camera / incident /
    person / journey / none). `step_index` is the 0-based index of the step we
    are currently waiting for; `step_deadline` is when that step lapses.
    """

    __tablename__ = "rule_sequence_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    correlation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # active | completed | expired
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    step_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Accumulated {trigger, steps:[...]} context for vars threading (later slice).
    vars: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Lookup live instances for a (rule, subject) on each observation.
        Index("ix_rule_seq_rule_status_key", "rule_id", "status", "correlation_key"),
        # Sweeper scan for overdue active instances.
        Index("ix_rule_seq_status_deadline", "status", "step_deadline"),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # Footage covering the observation, resolved at fire time by camera +
    # timestamp. Lets an alert consumer jump straight to the clip.
    # FK with ondelete="SET NULL" so retention deletes degrade gracefully
    # ("no clip" link) rather than leaving a dangling id (fixes #102).
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # Denormalized from the rule (and demotable by a failed verify) so the
    # alerts UI can filter without joining; camera_id denormalized from the
    # payload so per-camera triage does not parse JSON.
    severity: Mapped[str] = mapped_column(String(16), default="alert")
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_status: Mapped[str] = mapped_column(String(16), default="pending")
    action_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Phase 2 ack triad. Set in lockstep by either the Telegram callback
    # handler or POST /api/events/{id}/ack. ``acked_via`` is one of
    # ``telegram``, ``web``, or ``api``. Pre-existing ``acknowledged_at``
    # is left in place for back-compat with old admin tooling but new
    # code should read ``acked_at``.
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acked_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Per-event mute. Set by the "Mute 10 min" Telegram button. While
    # now() < muted_until, downstream Telegram re-sends for the
    # rule+camera combo of this event are skipped. Snooze wins over
    # mute because snooze is rule-wide.
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventNote(Base):
    """Free-text annotation on an Event.

    Phase 4. Replying to a Telegram alert lands here with
    ``source='telegram'``. The web UI also exposes POST + DELETE on
    these rows under /api/events/{id}/notes. Deleting is a hard delete;
    notes are cheap and the source row's history (Event) is preserved.
    """

    __tablename__ = "event_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # telegram | web | api
    text: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
