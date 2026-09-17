"""Guardian mode: a facility, the links that grant someone a scoped view
of it, approved pickups, and the access trail over both.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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


class Facility(Base):
    """The operator that owns cameras and grants guardian access.

    For a single-household self-host deploy, one default Facility is
    auto-created and every Person/Camera implicitly belongs to it. The model
    exists so the daycare/multi-tenant story is a config change, not a
    schema migration.
    """

    __tablename__ = "facilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)  # IANA, null = system default
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Facility-level overrides of the system guardian settings. Null = inherit.
    reveal_min_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cameras_per_person: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuardianLink(Base):
    """Binding of a guardian (User) to a dependant (Person). The spine.

    The privacy guarantee rests on this row. The facility grants and revokes;
    the guardian never self-grants. Each link is independently tiered,
    entitled, alert-configured, expirable, and revocable.
    """

    __tablename__ = "guardian_links"
    __table_args__ = (
        UniqueConstraint("guardian_user_id", "person_id", name="uq_guardian_person"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    guardian_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # mother, father, grandparent, carer
    relationship_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # full | summary | alerts_only  (see brief section 11)
    tier: Mapped[str] = mapped_column(String(16), default="full", nullable=False)
    # Per-link alert opt-ins within the facility-allowed set. booleans keyed by
    # alert kind: arrived, departed, picked_up, entered_zone, left_zone, not_seen.
    alert_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Channels this guardian receives alerts on. booleans keyed by
    # channel: telegram, email, in_app. Null = all available channels.
    notify_channels: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Entitlement flags (brief section 24.11). No billing yet; an admin toggles
    # these and they gate exactly as paid features will.
    premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # recap + smart search
    live_presence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # removes 30-min delay
    # blurred live clips, lifts image cap
    live_video: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # audio-derived signals
    # At least one primary parent paid unlocks free extra guardians on this person.
    is_primary_parent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Stricter-only per-link reveal override. May raise the floor, never lower it.
    reveal_min_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last time an image was served to this guardian, for the 1/hour free throttle.
    last_image_served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovedPickup(Base):
    """A person or vehicle approved to pick up a dependant.

    Verified pickup checks a departure event against this registry. A match
    yields "picked up by X"; a non-match yields a yellow "unrecognized pickup".
    """

    __tablename__ = "approved_pickups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="person", nullable=False)  # person | vehicle
    # When the approved pickup is a known Person in the system, link it so the
    # face engine confirms identity. Null for free-text/vehicle entries.
    linked_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuardianEvent(Base):
    """A guardian-facing event about a dependant (arrived, departed, picked_up,
    entered/left zone). Persisted when the fan-out fires so the panel can show a
    real day-timeline and a pickup-moment card, not just raw sightings.

    Keyed by person (the event is about the dependant); each of that person's
    guardians sees it filtered by their own delay/prefs at read time.
    """

    __tablename__ = "guardian_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # arrived | departed | picked_up | entered_zone | left_zone | not_seen
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    zone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # For pickups: was the escort on the approved list, and who.
    pickup_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pickup_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Evidence state of a pickup event, distinct from a staff-confirmed handover.
    # One of: possible | approved_match | confirmed | corrected. A camera-only
    # inference is never "confirmed"; only an explicit staff action sets that.
    # See services.guardian.handover for the state contract.
    handover_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GuardianHandoverConfirmation(Base):
    """Append-only audit of staff confirmations and corrections on a pickup.

    A camera inference (co-presence or a plate match) is never a completed
    handover. An authorized staff member confirms or corrects it here; each
    action records who, when, and the evidence they relied on. Corrections
    append a new row rather than overwriting, so the history is preserved
    (issue #191). The current state also lives denormalized on
    ``GuardianEvent.handover_state`` for cheap reads; this table is the trail.
    """

    __tablename__ = "guardian_handover_confirmations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guardian_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # confirmed | corrected
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    # The state the event held before this action, so a correction can be read.
    prior_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Free-form record of what the staff member relied on (clip id, plate, note).
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GuardianAccessLog(Base):
    """Append-only audit of every guardian view. Visible to the facility.

    Transparency is a feature (brief section 12). Every status check, image
    fetch, timeline view, live session, recap, and search is logged.
    """

    __tablename__ = "guardian_access_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guardian_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guardian_links.id", ondelete="CASCADE"), nullable=False, index=True
    )
    guardian_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # status | image | timeline | live | recap | search | alerts_change
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
