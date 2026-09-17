"""Per-user verified-activation milestones (#193 / #204 phase 2).

One row per (user, goal). It records the separate moments a goal became
configured, tested and confirmed-useful, plus the real event and delivery
that back the test. The state machine that reads these fields lives in
``shared.activation``; this is only the store.

Nothing here grants permission or changes a rule. A scaffolded draft rule
is referenced by id and is created disabled; the milestone never enables
it.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class ActivationMilestone(Base):
    __tablename__ = "activation_milestones"
    __table_args__ = (
        # A person pursues one instance of a goal at a time from the card.
        UniqueConstraint("user_id", "goal", name="uq_activation_user_goal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal: Mapped[str] = mapped_column(String(32), nullable=False)

    # The camera and rule the test is bound to. SET NULL so retention or a
    # deleted rule degrades to "needs reconfiguring", never a dangling id.
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )
    # The disabled rule a goal scaffolded, kept distinct from the rule the
    # user ultimately configured (they may differ if the user starts fresh).
    draft_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )

    # Milestone timestamps, each independently null until reached.
    configured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_useful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # "synthetic" (demo camera) or "real". Only a real, delivered, confirmed
    # test is verified activation.
    test_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # The real event and whether its alert was actually delivered.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    delivery_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # When the install became server-ready, so time-to-first-useful-result
    # can be measured apart from install time.
    install_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
