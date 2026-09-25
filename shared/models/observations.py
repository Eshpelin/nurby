"""What was seen. A raw observation, the actions read out of it, the
journeys it joins, and the incidents it rolls up into.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_camera_started", "camera_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    object_detections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    person_detections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Vehicle sightings in this frame. mirrors person_detections. shape.
    # {"vehicles": [{"bbox": [...], "label": "car", "plate_text": str|None,
    #   "vehicle_id": uuid|None, "identity_key": str, "confidence": float}],
    #  "count": int}. Drives the Vehicles tab the same way person_detections
    # drives People.
    vehicle_detections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vlm_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    vlm_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # DETECTION confidence, not caption confidence (#221). Holds the detector's
    # own score for the strongest object detection in the keyframe, in [0, 1], or
    # None when the frame carried no scored detection (motion-only). The VLM
    # caption does NOT contribute a confidence here: caption providers do not
    # expose a calibrated vision confidence uniformly, so no placeholder is
    # written. Any per-pass caption confidence lives on ObservationVlmPass.
    # Derived by services.perception.caption_schema.detection_confidence; see
    # that module for the full semantics every consumer must respect.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    clip_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Unannotated frame (no detection boxes) for downstream visual grounding.
    # Column added by migration a3f5c1e9d7b2; the mapped attribute was missing
    # here, so every observation write raised a TypeError and nothing landed.
    clean_frame_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description_embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    # Cascade history. When the refiner stage replaces the primary
    # text on this observation, the original primary output is moved
    # here so the UI can show a before/after comparison.
    primary_vlm_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    refined_by_provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    refined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Prompt provenance for the live caption (#218). Key + version resolve to
    # the exact text through services.perception.prompt_registry. The text is
    # stored only for a camera's own custom prompt, which the registry does
    # not hold. NULL on rows captioned before stamping existed: shown as
    # legacy/unknown rather than guessed.
    caption_prompt_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    caption_prompt_version: Mapped[str | None] = mapped_column(String(24), nullable=True)
    caption_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Primary incident link. Set by the perception pipeline at insert
    # time when incident tracking is enabled on the camera. Null means
    # the observation stands alone or tracking was off when it landed.
    #
    # An observation with several subjects in frame belongs to one
    # incident per subject; this column holds the strongest-rung one
    # (see incident_tracker.IDENTITY_LADDER). The full set lives in
    # ``observation_incidents``.
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # VLM backlog drift. When the VLM worker patches in the description
    # more than 60 seconds after the keyframe landed, vlm_late is set
    # and vlm_enqueued_at carries the original enqueue timestamp. The
    # UI shows a small clock icon on late captions; the agent's
    # summarize_activity rolls a 'pending' bucket from these.
    vlm_late: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vlm_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Idle enrichment bookkeeping. How many VLM passes (including the
    # original live pass) exist for this observation, and when the last
    # enrichment ran. Denormalized so candidate selection does not have
    # to aggregate observation_vlm_passes on every scan.
    enrich_pass_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ObservationAction(Base):
    """Structured per-person action for one observation frame.

    A parallel, queryable signal alongside ``Observation.vlm_description``. The
    perception pipeline classifies each recognised dependant's body crop into a
    closed action vocabulary (see ``services.perception.actions.ACTIONS``) and
    appends one row per person here. Unlike the prose caption, this is indexable,
    so "every meal Mum attended this week" or "did Dad fall" become real queries.

    Rows are written only for recognised dependants in frame (the action pass is
    gated on dependant presence to bound VLM cost), so ``person_id`` /
    ``person_name`` are normally set. ``action`` is always one of the closed
    vocabulary; ``posture`` is advisory; ``confidence`` is the model's own,
    nullable when the provider did not return one.
    """

    __tablename__ = "observation_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    person_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    posture: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Open-world description of what this person was doing, beyond the closed
    # action enum (objects held, clothing, finer activity). Free text from the
    # VLM, nullable. The closed action stays the queryable anchor; this holds the
    # nuance the enum cannot.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Which classification prompt produced this label (#218).
    prompt_key: Mapped[str] = mapped_column(String(64), default="legacy/unknown", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(24), default="legacy", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonActionSegment(Base):
    """A contiguous run of one action by one tracked person (HAR timeline source).

    Written by the HAR state machine on a transition (or on track loss): merged, debounced
    action runs with a start and an end. Unlike ``observation_actions`` (keyframe-anchored,
    one row per observation), this is **track-anchored and observation-independent** so it can
    capture continuous activity between keyframes. It is the cheap range-query source for the
    per-camera activity timeline and the wellbeing rollups.

    Identity is the held binding from ``identity_binding``: ``person_id`` is set only for a
    recognised, consented person; segments for unknown/body-only tracks either carry no
    ``person_id`` or are dropped before write, and are never shown on a guardian surface.
    Has its own age-based retention (``har_segment_retention_days``) because, unlike
    observations, continuous HAR would otherwise grow this table without bound.
    """

    __tablename__ = "person_action_segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    person_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # skeleton | skeleton+vlm | geometric — provenance for trust + the training set.
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ObservationVlmPass(Base):
    """A single versioned VLM pass over one observation's frame.

    Append-only. The original live caption is stored as ``pass_no=1,
    lens='live'``; idle enrichment appends later passes with different
    lenses. ``Observation.vlm_description`` stays authoritative and points
    at whichever pass the reduce step blesses (tracked by ``authoritative``
    here), but no pass is ever destroyed, so enrichment is fully
    reversible and auditable.
    """

    __tablename__ = "observation_vlm_passes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    pass_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # live | attributes | temporal | anomaly | reduce
    lens: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_key: Mapped[str] = mapped_column(String(64), default="legacy/unknown", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), default="v1", nullable=False)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured extraction. objects, colors, text/plates read, counts,
    # time-of-day cues. Drives search and rules in later phases.
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True for the pass currently surfaced as the observation's
    # authoritative caption. At most one per observation.
    authoritative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set true once a later reduce pass reconciles and replaces this one.
    superseded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("observation_id", "pass_no", name="ux_obs_pass_no"),
    )


class GroundingResult(Base):
    """A FindAnything visual-grounding result for one (observation, prompt).

    Append-only and query-dependent: grounding is ``prompt + frame -> boxes``,
    so one observation can be grounded by many prompts (design §7). Keyed by
    (observation_id, prompt_hash, model_revision) for idempotency. it doubles
    as the persistent cache (skip re-inference) AND the teach-the-index tag
    store (a located 'chicken' makes the next search for it instant). It is
    safe-by-default w.r.t. rules: the engine only evaluates live ``rule_data``
    and never re-runs against stored rows, so a written tag cannot retro-fire
    an automation (design §7.1).
    """

    __tablename__ = "grounding_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Normalized query text plus its hash (the cache/lookup key component).
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    found: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    corroborated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # [{"bbox_norm": [x1,y1,x2,y2], "is_point": bool, "label": str}, ...]
    boxes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "observation_id", "prompt_hash", "model_revision",
            name="ux_grounding_obs_prompt_rev",
        ),
    )


class Journey(Base):
    """Cross-camera story for one subject.

    Groups Incident rows for the same named person or face cluster
    across multiple cameras within an idle window. Segments are
    time-ordered slices of presence on each camera; transitions
    capture camera-to-camera movement gaps.
    """

    __tablename__ = "journeys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    segments: Mapped[dict] = mapped_column(JSON, nullable=False)
    transitions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cameras_seen_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    incidents_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    # When the associator folded this journey into entity associations.
    # Null means not yet processed. A column rather than a cursor so the
    # pass is idempotent and cannot skip a journey by drifting.
    associations_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Incident(Base):
    """Server-side rolling artifact that groups related observations.

    Signature key + camera + idle window define when an incident
    accepts another observation. The pipeline opens / extends rows
    inline at observation insert time. The finalizer worker closes
    rows whose ``last_seen_at`` is past the camera's idle window and
    optionally generates a summary.
    """

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signature_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    signature_key: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    peak_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="SET NULL"), nullable=True
    )
    observation_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thumbnails: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    journey_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journeys.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    # Resolution workflow (#197). "seen" (acknowledged) and "resolved" are
    # different outcomes: status tracks the latter. open | resolved | dismissed.
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    resolution_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Optional owner for business pilots. Households can ignore it.
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IncidentEvent(Base):
    """Append-only log of an incident's workflow transitions (#197).

    Durable ownership/audit: "who handled it and when" survives a reopen,
    unlike the single ``resolved_by`` pointer on ``Incident``. One row per
    action (resolved / dismissed / reopened / assigned / unassigned) with the
    actor, an optional reason, and a human ``detail`` (e.g. the assignee).
    """

    __tablename__ = "incident_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_incident_events_incident_created", "incident_id", "created_at"),
    )


class ObservationIncident(Base):
    """One observation's membership in one subject's incident.

    An observation can show several subjects at once. Before this table
    they were joined into a single signature ("Ahmed,Sara"), which is a
    different subject than "Ahmed" and therefore fragmented both people's
    history the moment they walked together (issue #145). Now each
    subject gets its own incident and this table records the membership.

    ``Observation.incident_id`` survives as the primary link, holding the
    strongest-rung subject, so every existing query keeps working
    unchanged. Read this table when you need all of them.

    ``subject_kind`` / ``subject_key`` duplicate the incident's signature
    on purpose: they record what this observation contributed, which stays
    true even if the incident is later merged or re-keyed. ``bound_by``
    carries the evidence rung (face / held / face_cluster / body).
    """

    __tablename__ = "observation_incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    bound_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # True for the row mirrored into Observation.incident_id.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "observation_id", "incident_id", name="uq_observation_incident"
        ),
    )
