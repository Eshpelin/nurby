"""Who and what Nurby recognises: people, their faces and bodies, the
clusters it groups them into, vehicles, and the habits linking them.

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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Household-wide colloquial name shown in place of display_name across
    # all view surfaces (notifications, digest, timeline, agent answers).
    # Purely presentational. Identity matching, journey signatures, and
    # cluster naming always use the canonical display_name.
    nickname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relationship: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Counts toward Home/Away presence (#184): when every household member has
    # left, auto mode flips to "away"; when one is seen again, back to "home".
    is_household_member: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which facility this person belongs to. Null = unscoped (every camera).
    facility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    privacy_blur: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    photo_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recap_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    recap_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recap_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recap_cached_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    recap_cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recap_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Agent v1 (resolution 5, docs/agent-design.md section 17). Marks
    # persons whose audio transcripts should be redacted before being
    # exposed to the agent. Lands now so v2 can flip without another
    # migration; tool layer reads it as a no-op until v2 wires it up.
    audio_redact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding = mapped_column(Vector(512), nullable=False)  # 512-dim InsightFace ArcFace embedding
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload | detection
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FaceCluster(Base):
    __tablename__ = "face_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # average embedding of cluster (InsightFace ArcFace)
    representative_embedding = mapped_column(Vector(512), nullable=False)
    sample_thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # best face crop
    sighting_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # linked once named
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, named, ignored
    auto_label_number: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)  # "Unknown 645"
    appearance_description: Mapped[str | None] = mapped_column(Text, nullable=True)  # VLM short demographics/clothing
    appearance_description_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, done, failed
    # Phase 4. Stamped once we DM a household admin asking them to name
    # this cluster. Stays null until then so the cluster-naming
    # initiator can lock-step against it without re-prompting.
    naming_prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FaceClusterSample(Base):
    __tablename__ = "face_cluster_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("face_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    embedding = mapped_column(Vector(512), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BodyCluster(Base):
    """Cross-camera body re-identification cluster.

    Sibling of FaceCluster. Built from OSNet appearance embeddings on
    full-person bounding boxes. Lets the system recognize the same
    individual across cameras even when the face is not visible, by
    matching clothing, body shape, and color.

    A BodyCluster carries `status` and `confidence`. A "tentative"
    cluster has not yet been face-confirmed. Once a co-occurring face
    cluster gets linked to the same `person_id`, the body cluster is
    promoted to "confirmed".
    """
    __tablename__ = "body_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    representative_embedding = mapped_column(Vector(512), nullable=False)
    representative_color: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sample_thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sighting_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    linked_face_cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("face_clusters.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), default="tentative", nullable=False)
    auto_label_number: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    appearance_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 4. Mirrors FaceCluster.naming_prompted_at.
    naming_prompted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BodyClusterSample(Base):
    __tablename__ = "body_cluster_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("body_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    embedding = mapped_column(Vector(512), nullable=False)
    color_histogram: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    bbox: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Vehicle(Base):
    """A tracked vehicle identity, the vehicle analogue of Person.

    Identity is keyed by ``identity_key``. the license plate when one was
    read (exact), otherwise a normalized appearance description such as
    "red forklift" (approximate, for plateless vehicles). The perception
    pipeline upserts a Vehicle per detected vehicle and links each sighting
    through ``Observation.vehicle_detections`` (mirrors person_detections),
    so sightings are queried from observations exactly like persons.
    """

    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stable dedupe key. plate text (uppercased, spaces stripped) or
    # "type:description" for plateless vehicles. Unique so the pipeline can
    # upsert without races.
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    license_plate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # car, truck, bus, motorcycle, van, forklift
    vehicle_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # VLM one-liner. "Red Nissan sedan with tinted windows". Generated once
    # per vehicle so it does not re-run every frame.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending, done, failed
    photo_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True until a human confirms/renames it. auto-created plate/appearance
    # vehicles start provisional so the UI can offer them as suggestions.
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sighting_count: Mapped[int] = mapped_column(Integer, default=1)
    # Plateless identity. a vehicle with no readable plate (forklift, car at
    # a bad angle) is re-identified by its CLIP appearance embedding instead.
    # plateless=True marks these, and appearance_embedding holds the running
    # representative so a recurring vehicle collapses to one row without a
    # plate. Plated vehicles leave both unset.
    plateless: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    appearance_embedding: Mapped[list[float] | None] = mapped_column(Vector(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntityAssociation(Base):
    """A learned or declared edge between two identities.

    Nothing in the schema recorded that two identities keep showing up
    together, so "which car does Ahmed use" and "is this operator
    authorized for that forklift" were unanswerable even though Person
    and Vehicle both carry stable identities (issue #148).

    Subjects are keyed the way journeys key them (``subject_kind`` /
    ``subject_key``, e.g. ``person`` / ``"Ahmed"``) so an edge joins
    straight onto the journey history it was derived from. Person display
    names carry a case-insensitive unique index, so that key is stable.
    Objects are keyed by row id, with ``object_label`` denormalized for
    display, so renaming a vehicle does not orphan its edges.

    ``source`` is the load-bearing field. A ``learned`` edge is inferred
    from co-presence and is a statement about habit. A ``declared`` edge
    is asserted by an administrator and is a statement about policy. They
    must never be conflated: an authorization is not something to infer
    from someone having driven a forklift twice.

    Promotion gates on ``distinct_days``, not ``evidence_count``. A van
    idling beside someone for twenty consecutive keyframes is one event,
    and counting observations would mint a permanent fact out of a single
    morning.

    Curator invariants, shared with the household-facts work: never
    auto-delete, only archive; the user can confirm or reject; a rejected
    edge is never revived by later evidence.
    """

    __tablename__ = "entity_associations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    object_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # uses | accompanies | arrives_with | authorized_for
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="uses")
    # learned (inferred from co-presence) | declared (asserted by an admin)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="learned")
    # candidate | established | archived | rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Last local calendar date folded in, as YYYY-MM-DD in household time.
    # Guards distinct_days against a second sighting the same day counting
    # as a second day.
    last_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 24 and 7 slot counters, in household-local time, so "he leaves around
    # 8am" is answerable without rescanning history.
    hour_histogram: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dow_histogram: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Where the pairing usually happens, keyed by camera id. "Someone else
    # is parked in your spot" is a claim about a place, so the edge has to
    # remember one.
    camera_histogram: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_kind", "subject_key", "object_kind", "object_key",
            "relation", "source",
            name="uq_entity_association",
        ),
    )
