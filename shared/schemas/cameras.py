"""Camera registration and recording schemas, including the
stream-URL allowlist that keeps network camera types off
non-camera schemes.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator


# ── Camera schemas ──

# Stream URL scheme allowlist, per stream_type. Path-based types (usb, file) use
# stream_url as a device index / local file path rather than a network URL, so they
# are intentionally not scheme-checked here. Mirrors Frigate's camera URL validation
# (PR #23352) and removes the file://, gopher://, dict:// … injection/SSRF surface
# for network camera types.
_STREAM_URL_SCHEMES: dict[str, set[str]] = {
    "rtsp": {"rtsp", "rtsps"},
    "webcam": {"rtsp", "rtsps"},
    "http_mjpeg": {"http", "https"},
    "http_snapshot": {"http", "https"},
    "hls": {"http", "https"},
}


_PATH_STREAM_TYPES = {"usb", "file"}


_NETWORK_SCHEMES = {"rtsp", "rtsps", "http", "https"}


def validate_stream_url(url: str, stream_type: str | None) -> str:
    """Reject stream URLs whose scheme is not allowed for the given stream type.

    Path-based types (usb, file) are passed through. For an unknown / forward-compat
    type we do not block. On a partial update where the type is omitted we tolerate
    bare paths and known network schemes but still reject dangerous schemes.
    """
    if stream_type in _PATH_STREAM_TYPES:
        return url
    scheme = urlparse(url).scheme.lower()
    if stream_type is None:
        if scheme == "" or scheme in _NETWORK_SCHEMES:
            return url
        allowed: set[str] = _NETWORK_SCHEMES
    else:
        allowed = _STREAM_URL_SCHEMES.get(stream_type, set())
        if not allowed or scheme in allowed:
            return url
    raise ValueError(
        f"stream_url scheme {scheme or '(none)'!r} is not allowed for stream_type "
        f"{stream_type or 'unspecified'!r}; allowed schemes: {sorted(allowed)}"
    )


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    stream_url: str = Field(min_length=1, max_length=1024)
    stream_type: str = Field(default="rtsp", max_length=32)  # rtsp, http_mjpeg, http_snapshot, hls, usb, file
    snapshot_url: str | None = Field(default=None, max_length=1024)
    location_label: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    auth_token: str | None = Field(default=None, max_length=512)
    snapshot_interval: float = Field(default=2.0, ge=0.5, le=60.0)
    motion_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    recording_enabled: bool = True
    recording_mode: str = "always"
    recording_trigger_objects: list[str] | None = None
    recording_clip_pre: int = Field(default=5, ge=1, le=30)
    recording_clip_post: int = Field(default=10, ge=1, le=60)
    vlm_provider_id: uuid.UUID | None = None
    vlm_prompt: str | None = Field(default=None, max_length=4096)
    vlm_interval: int = Field(default=0, ge=0, le=3600)
    vlm_max_tokens: int = Field(default=200, ge=50, le=2000)
    vlm_max_input_tokens: int | None = Field(default=None, ge=64, le=2_000_000)
    vlm_refiner_provider_id: uuid.UUID | None = None
    vlm_refiner_trigger_objects: list[str] | None = None
    vlm_refiner_keywords: list[str] | None = None
    vlm_refiner_max_tokens: int | None = Field(default=None, ge=50, le=2000)
    vlm_refiner_max_input_tokens: int | None = Field(default=None, ge=64, le=2_000_000)
    vlm_object_prompts: dict[str, str] | None = None
    detect_objects: bool = True
    detect_faces: bool = True
    detect_plates: bool = True
    detect_classes: list[str] | None = None  # per-camera override; None = inherit global
    scene_mode: str = Field(default="indoor", max_length=16)  # indoor, outdoor
    plateless_reid_enabled: bool | None = None  # None = auto (off outdoors)
    object_confidence: float = Field(default=0.35, ge=0.05, le=1.0)
    vlm_trigger: str = Field(default="always", max_length=16)  # always, on_object
    vlm_trigger_objects: list[str] | None = None
    detection_models: list[dict] | None = None
    detection_merge: str = Field(default="any", max_length=16)
    detection_consensus_min: int = Field(default=2, ge=1, le=10)
    digest_enabled: bool = True
    digest_period: str = "24h"
    digest_provider_id: uuid.UUID | None = None
    digest_prompt: str | None = Field(default=None, max_length=4096)
    retention_mode: str = Field(default="none", max_length=16)  # none, time, size
    retention_days: int = Field(default=30, ge=1, le=3650)
    retention_gb: float = Field(default=50.0, ge=1.0, le=10000.0)
    motion_zones: list[dict] | None = None
    webcam_device: str | None = Field(default=None, max_length=255)
    audio_only: bool = False
    exclude_from_review: bool = False
    enabled: bool = True
    privacy_zone_targets: list[str] | None = None
    privacy_zone_blur_strength: int = Field(default=55, ge=5, le=151)
    yolo_world_prompts: list[str] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    scene_baseline_detection_enabled: bool | None = None
    # Summary config
    summary_provider_id: uuid.UUID | None = None
    summary_mode: str = Field(default="off", max_length=16)
    summary_period_seconds: int = Field(default=1800, ge=60, le=86400)
    summary_event_quiet_seconds: int = Field(default=60, ge=5, le=3600)
    summary_event_trigger_objects: list[str] | None = None
    summary_event_min_duration_seconds: int = Field(default=5, ge=1, le=3600)
    summary_max_tokens: int = Field(default=400, ge=50, le=2000)
    # Conversation grouping
    conversation_gap_seconds: int = Field(default=30, ge=5, le=600)
    conversation_summary_enabled: bool = True
    conversation_min_messages_for_summary: int = Field(default=2, ge=1, le=20)
    incident_tracking_enabled: bool = True
    incident_idle_seconds: int = Field(default=600, ge=30, le=86400)

    @model_validator(mode="after")
    def _validate_stream_url(self):
        validate_stream_url(self.stream_url, self.stream_type)
        return self


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    stream_url: str | None = Field(default=None, min_length=1, max_length=1024)
    stream_type: str | None = Field(default=None, max_length=32)
    snapshot_url: str | None = Field(default=None, max_length=1024)
    location_label: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    auth_token: str | None = Field(default=None, max_length=512)
    snapshot_interval: float | None = Field(default=None, ge=0.5, le=60.0)
    motion_sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    recording_enabled: bool | None = None
    recording_mode: str | None = None
    # Per-camera storage location (issue #251). Null = global recordings
    # root; a profile id routes this camera's segments under that root.
    storage_profile_id: uuid.UUID | None = None
    recording_trigger_objects: list[str] | None = None
    recording_clip_pre: int | None = Field(default=None, ge=1, le=30)
    recording_clip_post: int | None = Field(default=None, ge=1, le=60)
    vlm_provider_id: uuid.UUID | None = None
    vlm_prompt: str | None = Field(default=None, max_length=4096)
    vlm_interval: int | None = Field(default=None, ge=0, le=3600)
    vlm_max_tokens: int | None = Field(default=None, ge=50, le=2000)
    vlm_max_input_tokens: int | None = Field(default=None, ge=64, le=2_000_000)
    vlm_refiner_provider_id: uuid.UUID | None = None
    vlm_refiner_trigger_objects: list[str] | None = None
    vlm_refiner_keywords: list[str] | None = None
    vlm_refiner_max_tokens: int | None = Field(default=None, ge=50, le=2000)
    vlm_refiner_max_input_tokens: int | None = Field(default=None, ge=64, le=2_000_000)
    vlm_object_prompts: dict[str, str] | None = None
    detect_objects: bool | None = None
    detect_faces: bool | None = None
    detect_plates: bool | None = None
    detect_classes: list[str] | None = None
    scene_mode: str | None = Field(default=None, max_length=16)
    plateless_reid_enabled: bool | None = None  # null = auto
    object_confidence: float | None = Field(default=None, ge=0.05, le=1.0)
    vlm_trigger: str | None = Field(default=None, max_length=16)
    vlm_trigger_objects: list[str] | None = None
    detection_models: list[dict] | None = None
    detection_merge: str | None = Field(default=None, max_length=16)
    detection_consensus_min: int | None = Field(default=None, ge=1, le=10)
    digest_enabled: bool | None = None
    digest_period: str | None = None
    digest_provider_id: uuid.UUID | None = None
    digest_prompt: str | None = Field(default=None, max_length=4096)
    retention_mode: str | None = Field(default=None, max_length=16)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    retention_gb: float | None = Field(default=None, ge=1.0, le=10000.0)
    motion_zones: list[dict] | None = None
    webcam_device: str | None = Field(default=None, max_length=255)
    audio_only: bool | None = None
    exclude_from_review: bool | None = None
    scene_baseline_detection_enabled: bool | None = None
    enabled: bool | None = None
    privacy_zone_targets: list[str] | None = None
    privacy_zone_blur_strength: int | None = Field(default=None, ge=5, le=151)
    yolo_world_prompts: list[str] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    display_order: int | None = None
    # Summary config
    summary_provider_id: uuid.UUID | None = None
    summary_mode: str | None = Field(default=None, max_length=16)
    summary_period_seconds: int | None = Field(default=None, ge=60, le=86400)
    summary_event_quiet_seconds: int | None = Field(default=None, ge=5, le=3600)
    summary_event_trigger_objects: list[str] | None = None
    summary_event_min_duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    summary_max_tokens: int | None = Field(default=None, ge=50, le=2000)
    # Conversation grouping
    conversation_gap_seconds: int | None = Field(default=None, ge=5, le=600)
    conversation_summary_enabled: bool | None = None
    conversation_min_messages_for_summary: int | None = Field(default=None, ge=1, le=20)
    incident_tracking_enabled: bool | None = None
    incident_idle_seconds: int | None = Field(default=None, ge=30, le=86400)
    # Smart Track
    ptz_smart_track_enabled: bool | None = None
    ptz_smart_track_targets: list[str] | None = None
    ptz_smart_track_ignore: list[str] | None = None
    ptz_smart_track_priority: list[str] | None = None
    ptz_smart_track_lost_seconds: int | None = Field(default=None, ge=1, le=300)
    ptz_smart_track_home_preset: str | None = Field(default=None, max_length=64)
    ptz_smart_track_zoom: bool | None = None
    ptz_smart_track_deadzone: float | None = Field(default=None, ge=0.0, le=0.5)
    ptz_smart_track_max_speed: float | None = Field(default=None, ge=0.05, le=1.0)
    ptz_smart_track_gain: float | None = Field(default=None, ge=0.1, le=5.0)
    ptz_smart_track_no_go: list[dict] | None = None
    ptz_smart_track_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ptz_smart_track_require_face: list[uuid.UUID] | None = None
    ptz_smart_track_move_budget_per_minute: int | None = Field(default=None, ge=1, le=600)
    ptz_profile_token: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _validate_stream_url(self):
        if self.stream_url is not None:
            validate_stream_url(self.stream_url, self.stream_type)
        return self


class CameraReorderItem(BaseModel):
    id: uuid.UUID
    display_order: int


class CameraResponse(BaseModel):
    id: uuid.UUID
    name: str
    stream_url: str
    stream_type: str
    storage_profile_id: uuid.UUID | None = None
    snapshot_url: str | None
    location_label: str | None
    has_credentials: bool = False
    snapshot_interval: float
    motion_sensitivity: float
    recording_enabled: bool
    recording_mode: str
    recording_trigger_objects: list[str] | None
    recording_clip_pre: int
    recording_clip_post: int
    vlm_provider_id: uuid.UUID | None
    vlm_prompt: str | None
    vlm_interval: int
    vlm_max_tokens: int
    vlm_max_input_tokens: int | None = None
    vlm_refiner_provider_id: uuid.UUID | None = None
    vlm_refiner_trigger_objects: list[str] | None = None
    vlm_refiner_keywords: list[str] | None = None
    vlm_refiner_max_tokens: int | None = None
    vlm_refiner_max_input_tokens: int | None = None
    vlm_object_prompts: dict[str, str] | None = None
    detect_objects: bool
    detect_faces: bool
    detect_plates: bool = True
    detect_classes: list[str] | None = None
    scene_mode: str
    plateless_reid_enabled: bool | None = None
    object_confidence: float
    vlm_trigger: str
    vlm_trigger_objects: list[str] | None
    detection_models: list[dict] | None
    detection_merge: str
    detection_consensus_min: int
    digest_enabled: bool
    digest_period: str
    digest_provider_id: uuid.UUID | None
    digest_prompt: str | None
    retention_mode: str
    retention_days: int
    retention_gb: float
    motion_zones: list[dict] | None
    status: str
    display_order: int = 0
    webcam_device: str | None = None
    audio_only: bool = False
    exclude_from_review: bool = False
    enabled: bool = True
    privacy_zone_targets: list[str] | None = None
    privacy_zone_blur_strength: int = 55
    yolo_world_prompts: list[str] | None = None
    timezone: str | None = None
    scene_baseline_detection_enabled: bool = False
    content_health_enabled: bool = False
    freeze_detection_enabled: bool = True
    obscuration_detection_enabled: bool = True
    scene_change_detection_enabled: bool = False
    health_status: str = "healthy"
    health_reason: str | None = None
    summary_provider_id: uuid.UUID | None = None
    summary_mode: str = "off"
    summary_period_seconds: int = 1800
    summary_event_quiet_seconds: int = 60
    summary_event_trigger_objects: list[str] | None = None
    summary_event_min_duration_seconds: int = 5
    summary_max_tokens: int = 400
    conversation_gap_seconds: int = 30
    conversation_summary_enabled: bool = True
    conversation_min_messages_for_summary: int = 2
    incident_tracking_enabled: bool = True
    incident_idle_seconds: int = 600
    ptz_smart_track_enabled: bool = False
    ptz_smart_track_targets: list[str] | None = None
    ptz_smart_track_ignore: list[str] | None = None
    ptz_smart_track_priority: list[str] | None = None
    ptz_smart_track_lost_seconds: int = 3
    ptz_smart_track_home_preset: str | None = None
    ptz_smart_track_zoom: bool = False
    ptz_smart_track_deadzone: float = 0.15
    ptz_smart_track_max_speed: float = 0.5
    ptz_smart_track_gain: float = 1.5
    ptz_smart_track_no_go: list[dict] | None = None
    ptz_smart_track_min_confidence: float = 0.45
    ptz_smart_track_require_face: list[uuid.UUID] | None = None
    ptz_smart_track_move_budget_per_minute: int = 30
    ptz_profile_token: str = "Profile_1"
    width: int | None
    height: int | None
    fps: float | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Camera status log schemas ──

class CameraStatusLogResponse(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    status: str
    previous_status: str | None
    reason: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Recording schemas ──

class RecordingResponse(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    file_path: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None
    file_size_bytes: int | None
    thumbnail_path: str | None
    blur_status: str = "pending"
    blur_error: str | None = None

    model_config = {"from_attributes": True}


# -- Storage profiles (issue #251) --

class StorageProfileCreate(BaseModel):
    """A named media-storage location. kind="local" is an absolute
    directory on a filesystem the backend can see; kind="ftp" is a native
    FTP server (config: host, port, username, password, passive, tls,
    delete_after_upload) — the root is the remote base directory."""

    name: str = Field(min_length=1, max_length=120)
    root: str = Field(min_length=1, max_length=1024)
    kind: str = Field(default="local", pattern="^(local|smb|nfs|ftp|s3|webdav)$")
    config: dict | None = None


class StorageProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    root: str | None = Field(default=None, min_length=1, max_length=1024)
    enabled: bool | None = None
    config: dict | None = None


class StorageProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    root: str
    enabled: bool
    created_at: datetime
    # Kind-specific settings with the password stripped; has_password
    # tells the UI a stored credential exists without exposing it.
    config: dict | None = None
    has_password: bool = False

    model_config = {"from_attributes": True}
