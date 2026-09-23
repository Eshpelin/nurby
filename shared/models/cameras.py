"""Cameras and what they physically are: their streams, their status
history, their recordings, their privacy zones and their speakers.

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


class StorageProfile(Base):
    """A named media-storage location a camera can record into (issue #251).

    v1 implements ``kind="local"``: ``root`` is an absolute directory on a
    filesystem the backend can see — a second drive, a mounted SMB/NFS
    share, an rclone mount over FTP/S3/WebDAV. ``kind`` stays textual so
    native remote backends (a write-through FTP/S3 uploader with its own
    playback story) can slot in later without a migration; until then,
    "my own FTP" is answered by mounting it and pointing a profile at the
    mount. See docs/storage-architecture.md.

    Resolution order per camera: its profile's root, else the global
    recordings root (storage_recordings_dir override or env default).
    """

    __tablename__ = "storage_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    root: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Kind-specific connection settings (FTP: host/port/username/passive/
    # tls/delete_after_upload), JSON with the password sealed via the same
    # Fernet cipher as camera credentials. Null for kind="local".
    config_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stream_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    # rtsp, http_mjpeg, http_snapshot, hls, usb, file
    stream_type: Mapped[str] = mapped_column(String(32), default="rtsp")
    snapshot_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Which facility exposes this camera. Null = unscoped (visible to all
    # facilities), preserving single-household behaviour.
    facility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # password and auth_token are Fernet-sealed at rest (shared/camera_secrets).
    # Width covers the token overhead for long credentials.
    password: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    snapshot_interval: Mapped[float] = mapped_column(Float, default=2.0)  # seconds between snapshot pulls
    motion_sensitivity: Mapped[float] = mapped_column(Float, default=0.5)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # deprecated, use recording_mode
    recording_mode: Mapped[str] = mapped_column(String(16), default="always")  # off, always, on_motion, on_object, clip
    recording_trigger_objects: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # labels for on_object mode
    recording_clip_pre: Mapped[int] = mapped_column(Integer, default=5)  # pre-capture (pre-roll) seconds for record-on-trigger modes (clip/on_motion/on_object)
    recording_clip_post: Mapped[int] = mapped_column(Integer, default=10)  # post-capture (post-roll) seconds for record-on-trigger modes (clip/on_motion/on_object)
    # Per-camera perception config
    vlm_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vlm_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)  # custom system prompt override
    vlm_interval: Mapped[int] = mapped_column(Integer, default=0)  # seconds between VLM calls, 0 = every keyframe
    vlm_max_tokens: Mapped[int] = mapped_column(Integer, default=200)
    vlm_max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-object-class prompt guidance. A {label: guidance} map (e.g.
    # {"person": "describe clothing and whether carrying anything",
    # "car": "note make, colour, and plate region"}). Nurby's VLM is
    # scene-level (one call per keyframe over all detections), so at
    # prompt-build time the guidance snippets for whichever labels are
    # present in the frame are unioned into a "pay special attention to"
    # section. Mirrors Frigate's per-camera genai object_prompts (#13767).
    vlm_object_prompts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Cascade refiner. When set, the primary VLM's output is post-
    # processed by the refiner provider whenever a trigger matches.
    vlm_refiner_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True
    )
    vlm_refiner_trigger_objects: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vlm_refiner_keywords: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vlm_refiner_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vlm_refiner_max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detect_objects: Mapped[bool] = mapped_column(Boolean, default=True)
    detect_faces: Mapped[bool] = mapped_column(Boolean, default=True)
    # License-plate OCR on detected vehicles. A "basic" that is on by default.
    detect_plates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Per-camera object-class allowlist override. None = inherit the global
    # detect_classes setting; [] = detect everything on this camera; a list =
    # only those labels here.
    detect_classes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scene_mode: Mapped[str] = mapped_column(String(16), default="indoor")  # indoor, outdoor
    # Per-camera plateless vehicle grouping (CLIP appearance re-id). Tri-state.
    # None = auto (on unless the camera is outdoor, where a busy street would
    # spawn too many transient identities). True/False force it. plated
    # vehicles are unaffected.
    plateless_reid_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    object_confidence: Mapped[float] = mapped_column(Float, default=0.35)  # YOLO confidence threshold
    # VLM trigger config
    vlm_trigger: Mapped[str] = mapped_column(String(16), default="always")  # always, on_object
    vlm_trigger_objects: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # e.g. ["person", "cat"]
    # Multi-model detection config
    # list of {"model", "confidence", "enabled", "label_filter"}
    detection_models: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detection_merge: Mapped[str] = mapped_column(String(16), default="any")  # any, consensus, best
    # min models that must agree for consensus mode
    detection_consensus_min: Mapped[int] = mapped_column(Integer, default=2)
    # Per-camera digest config
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_period: Mapped[str] = mapped_column(String(16), default="24h")  # 1h, 6h, 12h, 24h, 48h, 7d
    digest_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    digest_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Retention policy
    retention_mode: Mapped[str] = mapped_column(String(16), default="none")  # none, time, size
    retention_days: Mapped[int] = mapped_column(Integer, default=30)  # days to keep recordings
    retention_gb: Mapped[float] = mapped_column(Float, default=50.0)  # max GB per camera
    # Motion zones: [{"name": "Zone 1", "points": [[x,y], ...], "type": "include"|"exclude"}]
    motion_zones: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="offline")
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    webcam_device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Hide this camera from the review/alerts/timeline feed and its
    # filters. The camera keeps recording and stays a valid recording
    # target; only the review surfaces drop it. Distinct from the
    # dashboard camera-wall hide, which is a per-browser layout choice.
    exclude_from_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Content-health detection (#212): flag a frozen/obscured/tampered view
    # that keeps the stream "online" while coverage is silently gone. Master
    # switch off by default; each detection path pre-armed so enabling the
    # master is enough. See services/ingestion/content_health.py.
    content_health_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    freeze_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    obscuration_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scene_change_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Master enable/disable. When False the ingestion manager will not
    # start (or will tear down) all workers for this camera: stream,
    # audio, STT, and MediaMTX path. The camera row is kept intact so
    # config and history are preserved. Mirrors Frigate PRs #16894/#16920.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Per-camera storage (issue #251). Null = the camera records under the
    # global recordings root (env default or the storage_recordings_dir
    # override); set = the camera's segments land under the profile's root,
    # resolved by shared/storage_paths.recordings_root_for.
    storage_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("storage_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Audio-only mode. When true the ingestion + perception pipelines
    # skip video decode and run only the audio path (VAD, STT, audio
    # events, clap pattern, speech phrase). UI hides the video tile.
    audio_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Smart privacy zones. AI auto-detects regions on every keyframe
    # matching one of these target labels and blurs them before the
    # frame is encoded for VLM, thumbnail, or recording.
    privacy_zone_targets: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    privacy_zone_blur_strength: Mapped[int] = mapped_column(Integer, default=55, nullable=False)
    # YOLO-World v2 prompt list. Plain-English class names this
    # camera should detect. Only consulted when a yolov8*-worldv2
    # model is in the detection_models list.
    yolo_world_prompts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # IANA timezone string for this camera. Null = use the system
    # timezone setting. Drives timestamp rendering + daily digest
    # anchor selection.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Audio transcription config. On by default for new cameras (a "basic"),
    # but only captures when the stream actually carries audio. Existing
    # cameras keep their stored value; users can toggle it on the camera's
    # Audio page. Audio capture is privacy/consent-sensitive.
    audio_capture_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    audio_transcribe_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    audio_store_raw: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # full, redacted, summary_only
    transcript_store: Mapped[str] = mapped_column(String(16), default="full", nullable=False)
    audio_language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    audio_retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    # Voice output (#155). Default off: a camera that can talk is a
    # camera that can leak, so speaking is opt-in per camera even once
    # the household has enabled it globally.
    speaker_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Overrides the probed transport when a household knows better than
    # the probe did. Null means "use whatever was probed".
    speaker_transport: Mapped[str | None] = mapped_column(String(32), nullable=True)
    speaker_voice: Mapped[str | None] = mapped_column(String(64), nullable=True)
    speaker_volume: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    # Per-camera override of the household quiet hours, "HH:MM" local.
    speaker_quiet_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    speaker_quiet_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    speaker_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    speaker_daily_cap: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    # Endpoint for the http_device transport: an external speaker that is
    # not the camera. Sealed, since it can carry a token.
    speaker_endpoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transcript_retention_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    stt_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stt_budget_minutes_per_hour: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # STT accuracy/speed knobs. Defaults match the original behavior, so a
    # camera left alone transcribes exactly as before. Raise beam_size for
    # better accuracy on noisy audio at a CPU cost. condition_on_previous
    # carries context across segments (more coherent long speech, but can
    # propagate a transcription error). no_speech_threshold gates silence.
    audio_stt_beam_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    audio_stt_condition_on_previous_text: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    audio_stt_no_speech_threshold: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    # Summarization config (window-level VLM recap)
    summary_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL"), nullable=True
    )
    summary_mode: Mapped[str] = mapped_column(String(16), default="off", nullable=False)  # off, periodic, event, both
    summary_period_seconds: Mapped[int] = mapped_column(Integer, default=1800, nullable=False)  # 30 min default
    summary_event_quiet_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    # YOLO labels e.g. ["person"]
    summary_event_trigger_objects: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_event_min_duration_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    summary_max_tokens: Mapped[int] = mapped_column(Integer, default=400, nullable=False)
    # Conversation grouping (audio rollup)
    conversation_gap_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    conversation_summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    conversation_min_messages_for_summary: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    # Incident tracking. Persistent server-side grouping of related
    # observations into one rolling artifact with a stable id.
    incident_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    incident_idle_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    # Smart Track. Auto-follow detections via ONVIF PTZ. Reads
    # detections from the perception pipeline, sends ContinuousMove
    # commands to keep the target near frame center, returns to home
    # preset after `lost_seconds` of no target.
    ptz_smart_track_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ptz_smart_track_targets: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # labels to follow
    ptz_smart_track_ignore: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # labels to never follow
    ptz_smart_track_priority: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # tie-break order
    ptz_smart_track_lost_seconds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    ptz_smart_track_home_preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ptz_smart_track_zoom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ptz_smart_track_deadzone: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    ptz_smart_track_max_speed: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    ptz_smart_track_gain: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    # Optional ONVIF angle no-go boxes. [{"pan_min":..,"pan_max":..,"tilt_min":..,"tilt_max":..}]
    ptz_smart_track_no_go: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ptz_smart_track_min_confidence: Mapped[float] = mapped_column(Float, default=0.45, nullable=False)
    # Optional. Only follow these Person UUIDs (via face match).
    ptz_smart_track_require_face: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Mechanical wear cap. Max ContinuousMove commands per minute.
    ptz_smart_track_move_budget_per_minute: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # ONVIF media profile token. Most cameras use "Profile_1".
    ptz_profile_token: Mapped[str] = mapped_column(String(64), default="Profile_1", nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CameraStatusLog(Base):
    __tablename__ = "camera_status_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # offline, live, recording, error
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # e.g. "stream disconnected", "reconnected"
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MotionSample(Base):
    """Downsampled per-camera motion-score time series.

    Written from the existing motion pipeline (the perception keyframe path),
    NOT a second detector. Each row is one 1-second bucket carrying the peak
    motion score seen in that second (0..1). Sub-second duplicates within a
    bucket are coalesced via an upsert on (camera_id, bucket) that keeps the
    max score, so write volume is bounded to at most one row per camera-second
    regardless of frame rate.

    Read side (GET /cameras/{id}/motion) re-aggregates these 1s buckets into
    coarser caller-chosen buckets server-side (see services.api.motion_query),
    mirroring Frigate's optimized motion-activity endpoint (#23383).

    Retention: an age-based sweep in the hourly ingestion retention loop
    (RetentionManager._enforce_motion_sample_retention) bulk-deletes buckets
    older than ``motion_series_retention_days`` (#37), so the table stays bounded
    once the writer is enabled.
    """

    __tablename__ = "motion_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Timestamp truncated to the 1-second write bucket (UTC).
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Peak motion score in this bucket, 0..1.
    score: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        # One row per camera per second. Upsert target for max-score coalescing.
        UniqueConstraint("camera_id", "bucket", name="uq_motion_samples_camera_bucket"),
        # Range scans are always (camera_id, time-window); composite covers them.
        Index("ix_motion_samples_camera_bucket", "camera_id", "bucket"),
    )


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Clean keyframe (no detection boxes burned in) for visual grounding, so
    # FindAnything localizes real pixels, not a drawn rectangle. Null falls back
    # to thumbnail_path. Only written when detections were drawn (else identical).
    clean_frame_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    blur_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    blur_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Remote storage (issue #269, FTP profiles). Null remote_state = the
    # recording is local-only (no FTP profile at write time). pending rows
    # are picked up by the ingestion upload worker; uploaded recordings may
    # no longer exist locally (delete_after_upload) and are served from the
    # remote via an on-demand cache. remote_profile_id snapshots WHICH
    # profile handled the upload so retention can clean up the remote even
    # after the camera moves to a different profile.
    remote_state: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    remote_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    remote_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    remote_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    remote_error: Mapped[str | None] = mapped_column(String(512), nullable=True)


class PrivacyZone(Base):
    """Per-camera private region. Polygon stored in normalized 0-1
    coordinates so the same zone applies across resolution changes.

    ``source`` distinguishes ``auto`` (AI-proposed) from ``manual``
    (user-drawn). ``locked`` makes the zone immune to the auto
    refresh path so the user can pin a tight bathroom door bbox
    without the detector overwriting it on the next frame.
    """

    __tablename__ = "privacy_zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    polygon: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # PTZ pose at detection time. {pan, tilt, zoom} or null. Cameras
    # without PTZ leave this null and rely on freshness alone.
    ptz_pose: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Freshness gate. Auto zones not re-detected within this window
    # stop applying so a camera that panned away does not keep blurring
    # the wrong region. Manual and locked zones ignore it.
    stale_after_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)


class Device(Base):
    """User-registered physical alert device (buzzer, relay, speaker).

    Gives hardware an identity: rules reference ``device_id`` and the
    endpoint/secret/payload resolve from this row at fire time, so
    renaming a device or rotating its secret retargets every rule with
    no rule edits. ``preset_id`` links back to the static catalog entry
    (integrations/devices/catalog.py) the device was set up from, or is
    null for a custom endpoint. The secret is the shared HMAC key the
    receiver sketch verifies; sealed with the tolerant camera cipher so
    a jwt_secret rotation degrades to firing with the stored value
    instead of failing at alarm time.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    preset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    endpoint_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # None -> snapshot of the preset payload at creation -> engine default.
    payload_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SpeakerCapability(Base):
    """What a camera can actually be made to say, as probed (issue #153).

    Deliberately its own table rather than columns on ``Camera``. This is
    *discovered*, not configured, and conflating the two makes it
    impossible to tell "we have not looked yet" (no row) from "we looked
    and it cannot" (``supported=False``) from "it can but the household
    turned it off" (``Camera.speaker_enabled``). Those three need
    different words in the UI.

    A row is written whether the probe succeeds or fails. A failed probe
    is a finding, not an absence, and ``detail`` keeps the raw evidence so
    a later look does not have to re-run against hardware to know what was
    seen.
    """

    __tablename__ = "speaker_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # onvif_backchannel | hikvision | dahua | reolink | tapo |
    # http_device | none
    transport: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # RTP payload name the camera offered: pcmu, pcma, l16, aac.
    codec: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Where to send audio, when the probe found a specific endpoint.
    endpoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    probed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    probe_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
