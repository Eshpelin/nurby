"""Users, auth tokens, pairing, invites, providers, camera
sharing and access, push devices, system settings and
household mode: the account-level surface.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import re
import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


# ── Provider schemas ──

class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=32)
    base_url: str = Field(min_length=1, max_length=1024)
    api_key: str | None = Field(default=None, max_length=512)
    default_model: str | None = Field(default=None, max_length=255)
    active: bool = True
    # NULL = no cap, defer to the provider's model default.
    max_input_tokens: int | None = Field(default=None, ge=64, le=2_000_000)
    max_output_tokens: int | None = Field(default=None, ge=16, le=200_000)
    # ── Optional reasoning / "thinking" controls (issue #41) ───────────
    # All NULL by default → behavior unchanged. See shared.reasoning.
    anthropic_thinking: str | None = Field(default=None, pattern=r"^(adaptive|enabled|off)$")
    anthropic_thinking_budget_tokens: int | None = Field(default=None, ge=1024, le=200_000)
    openai_reasoning_effort: str | None = Field(default=None, pattern=r"^(minimal|low|medium|high)$")


class ProviderResponse(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    base_url: str
    default_model: str | None
    active: bool
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    anthropic_thinking: str | None = None
    anthropic_thinking_budget_tokens: int | None = None
    openai_reasoning_effort: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SystemSettingsResponse(BaseModel):
    """Safe-to-expose subset of runtime flags. Mirrors the whitelist
    in ``services/api/routes/system.py``."""

    system_timezone: str | None = None
    journey_idle_seconds: int = 300
    daily_digest_enabled: bool = True
    daily_digest_hour: int = 7
    nudity_blur: bool = True
    detect_classes: list[str] | None = None
    audio_events: bool = True
    body_reid_tentative_decay_days: int = 14
    cluster_naming_min_sightings: int = 3
    public_base_url: str | None = None
    rules_cooldown_backend: str = "redis"
    onboarding_dismissed: bool = False
    setup_checklist_dismissed: bool = False
    vlm_enrichment_enabled: bool = True
    vlm_enrichment_budget_minutes_per_hour: int = 20
    vehicle_appearance_match_min_similarity: float = 0.90
    guardian_enabled: bool = True
    guardian_free_delay_seconds: int = 1800
    guardian_free_image_interval_seconds: int = 3600
    guardian_reveal_min_confidence: float = 0.90
    guardian_max_cameras_per_person: int = 12
    guardian_pickup_detection_enabled: bool = True
    guardian_pickup_window_seconds: int = 120
    guardian_image_blur_radius: int = 12
    guardian_unblurred_clips_enabled: bool = False
    # FindAnything / visual grounding.
    grounding_enabled: bool = False
    grounding_backend: str = "local"
    grounding_remote_url: str | None = None
    # Mobile push (FCM). Only the non-secret Firebase client config is
    # readable; the service account is write-only (it holds a private
    # key) and is deliberately absent from this response model.
    push_firebase_client_config: dict | None = None
    # MQTT / Home Assistant (docs/integrations/mqtt.md). mqtt_password is
    # write-only (Fernet-sealed at rest) and deliberately absent here.
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_tls: bool = False
    mqtt_topic_prefix: str = "nurby"
    mqtt_client_id: str = "nurby"
    mqtt_discovery_enabled: bool = True
    mqtt_stats_interval: int = 60
    mqtt_camera_frame_interval: int = 10
    # Media storage location (issue #251). Null = env-provided default.
    storage_recordings_dir: str | None = None


class SystemSettingsUpdate(BaseModel):
    """Partial-update body for PATCH /api/system/settings. Pydantic's
    ``extra=forbid`` makes the route reject typos and stray keys with
    a 422 before our whitelist check even runs."""

    model_config = ConfigDict(extra="forbid")

    system_timezone: str | None = None
    journey_idle_seconds: int | None = Field(default=None, ge=1, le=24 * 3600)
    daily_digest_enabled: bool | None = None
    daily_digest_hour: int | None = Field(default=None, ge=0, le=23)
    nudity_blur: bool | None = None
    detect_classes: list[str] | None = None
    audio_events: bool | None = None
    body_reid_tentative_decay_days: int | None = Field(default=None, ge=0, le=3650)
    cluster_naming_min_sightings: int | None = Field(default=None, ge=0, le=1000)
    public_base_url: str | None = None
    rules_cooldown_backend: str | None = Field(default=None, pattern="^(redis|memory)$")
    onboarding_dismissed: bool | None = None
    setup_checklist_dismissed: bool | None = None
    vlm_enrichment_enabled: bool | None = None
    vlm_enrichment_budget_minutes_per_hour: int | None = Field(default=None, ge=0, le=600)
    vehicle_appearance_match_min_similarity: float | None = Field(default=None, ge=0.5, le=1.0)
    guardian_enabled: bool | None = None
    guardian_free_delay_seconds: int | None = Field(default=None, ge=0, le=24 * 3600)
    guardian_free_image_interval_seconds: int | None = Field(default=None, ge=0, le=24 * 3600)
    guardian_reveal_min_confidence: float | None = Field(default=None, ge=0.5, le=1.0)
    guardian_max_cameras_per_person: int | None = Field(default=None, ge=1, le=1000)
    guardian_pickup_detection_enabled: bool | None = None
    guardian_pickup_window_seconds: int | None = Field(default=None, ge=10, le=1800)
    guardian_image_blur_radius: int | None = Field(default=None, ge=1, le=100)
    guardian_unblurred_clips_enabled: bool | None = None
    # FindAnything / visual grounding.
    grounding_enabled: bool | None = None
    grounding_backend: str | None = Field(default=None, pattern="^(local|remote)$")
    grounding_remote_url: str | None = None
    # Mobile push (FCM). Paste-in JSON blobs from the Firebase console:
    # the service account (Project settings -> Service accounts) powers
    # server-side sends; the client config (apiKey / appId / projectId /
    # messagingSenderId) is handed to mobile apps via GET /api/push/config.
    push_fcm_service_account: dict | None = None
    push_firebase_client_config: dict | None = None
    # MQTT / Home Assistant. The password is sealed with the camera
    # credential cipher by the route before it lands in app_settings and
    # is never echoed back (absent from SystemSettingsResponse).
    mqtt_enabled: bool | None = None
    mqtt_host: str | None = Field(default=None, max_length=255)
    mqtt_port: int | None = Field(default=None, ge=1, le=65535)
    mqtt_username: str | None = Field(default=None, max_length=255)
    mqtt_password: str | None = Field(default=None, max_length=1024)
    mqtt_tls: bool | None = None
    mqtt_topic_prefix: str | None = Field(default=None, max_length=64, pattern="^[A-Za-z0-9_./-]*$")
    mqtt_client_id: str | None = Field(default=None, max_length=64, pattern="^[A-Za-z0-9_.-]*$")
    mqtt_discovery_enabled: bool | None = None
    mqtt_stats_interval: int | None = Field(default=None, ge=5, le=86400)
    mqtt_camera_frame_interval: int | None = Field(default=None, ge=0, le=3600)
    # Media storage location. Absolute POSIX or Windows drive path; the
    # validate endpoint enforces the shape before this is stored.
    storage_recordings_dir: str | None = Field(default=None, max_length=1024)


# -- User schemas --

class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    invite_key: str = Field(min_length=1, max_length=64)


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=72)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    camera_access_mode: Literal["all", "selected", "none"] = "none"
    is_active: bool
    # True for the auto-created first-run owner that has not yet set a
    # real email + password. Drives the "Secure your account" prompt.
    is_provisional: bool = False
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


# Pragmatic email shape check. Not full RFC 5322, just enough to stop a
# malformed value from being stored as the login email, which would lock
# the owner out (they could never type a matching string at /login).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountClaim(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    camera_access_mode: Literal["all", "selected", "none"] | None = None

    @field_validator("camera_access_mode")
    @classmethod
    def _non_null_camera_mode(cls, value):
        if value is None:
            raise ValueError("Choose all, selected, or none")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    # Present only on the first bootstrap response. The Settings endpoint
    # provides it later to the authenticated provisional owner.
    setup_code: str | None = None


class SetupCodeAdoption(BaseModel):
    code: str = Field(min_length=6, max_length=16, pattern=r"^[A-Za-z0-9-]+$")


class PairStartResponse(BaseModel):
    # Short-lived single-use pairing code the web app embeds in a QR code.
    code: str
    expires_in: int
    # Externally-reachable API base URL when the deployment configured one
    # (settings.public_base_url); the frontend falls back to a guess.
    server_url: str | None = None


class PairClaim(BaseModel):
    code: str = Field(min_length=1, max_length=2048)


class AdminSetup(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


# -- Invite key schemas --

class InviteKeyCreate(BaseModel):
    role: str = "viewer"
    camera_ids: list[uuid.UUID] | None = None
    max_uses: int = 1
    expires_at: datetime | None = None


class InviteCreatorInfo(BaseModel):
    """Minimal identity of the admin who created an invite key."""
    id: uuid.UUID
    email: str
    display_name: str | None = None


class InviteRedemptionInfo(BaseModel):
    """One account that was created by redeeming an invite key.

    ``redeemed_at`` is the user's account creation time, which is exactly the
    moment they redeemed the key (accounts can only be born via redemption).
    """
    user_id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
    is_active: bool
    redeemed_at: datetime


class InviteKeyResponse(BaseModel):
    id: uuid.UUID
    key: str
    role: str
    camera_ids: list[uuid.UUID] | None
    max_uses: int
    use_count: int
    expires_at: datetime | None
    created_at: datetime
    # Audit context for the redesigned Invite Keys UI. Populated by the list
    # route; both default empty/None so any code building a bare response
    # (tests, the create route returning the ORM row) stays valid.
    created_by: InviteCreatorInfo | None = None
    redemptions: list[InviteRedemptionInfo] = []

    model_config = {"from_attributes": True}


# -- Camera access schemas --

class UserCameraAccessResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    camera_id: uuid.UUID
    granted_at: datetime

    model_config = {"from_attributes": True}


class CameraShareRequest(BaseModel):
    user_ids: list[uuid.UUID]


class SetCameraAccessRequest(BaseModel):
    camera_ids: list[uuid.UUID]


# ── Device registry (@ mentions / physical alert devices) ──────────


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    preset_id: str | None = Field(default=None, max_length=64)
    endpoint_url: str = Field(min_length=1, max_length=1024)
    # Write-only shared HMAC secret; responses only ever say has_secret.
    secret: str | None = Field(default=None, max_length=1024)
    payload_template: dict | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=60)
    enabled: bool = True

    @field_validator("endpoint_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("endpoint_url must be an http(s) URL")
        return v


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    preset_id: str | None = Field(default=None, max_length=64)
    endpoint_url: str | None = Field(default=None, max_length=1024)
    # Absent = unchanged; empty string = clear (camera-route convention).
    secret: str | None = Field(default=None, max_length=1024)
    payload_template: dict | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    enabled: bool | None = None

    @field_validator("endpoint_url")
    @classmethod
    def _http_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("endpoint_url must be an http(s) URL")
        return v


# services/api/routes/push.py defines its own DeviceResponse, so FastAPI
# qualifies both OpenAPI component names by module. The core-schema ref
# below is what the served OpenAPI called this class when it lived in
# shared/schemas.py; overriding it keeps that component name stable.
class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        schema = handler(source_type)
        schema["ref"] = "shared.schemas.DeviceResponse"
        return schema

    id: uuid.UUID
    name: str
    preset_id: str | None
    endpoint_url: str
    has_secret: bool = False
    payload_template: dict | None
    timeout_seconds: int
    enabled: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_error: str | None
    created_at: datetime


# ── Household mode (#184) ──

class HouseholdModeChangeResponse(BaseModel):
    id: uuid.UUID
    mode: str
    previous_mode: str | None
    source: str
    changed_by_user_id: uuid.UUID | None
    changed_by_name: str | None = None
    note: str | None
    changed_at: datetime

    model_config = {"from_attributes": True}


class HouseholdModeResponse(BaseModel):
    """The current mode plus what the clients need to render a control."""

    mode: str
    since: datetime | None
    source: str | None
    # All modes, in display order, with the wording the UI shows.
    modes: list[dict]
    # Most recent changes, newest first.
    history: list[HouseholdModeChangeResponse] = Field(default_factory=list)
    # How many enabled rules are silenced by the current mode. Lets the
    # control say "3 rules paused" without a second request.
    silenced_rule_count: int = 0


class HouseholdModeUpdate(BaseModel):
    mode: str = Field(pattern="^(home|away|night)$")
    note: str | None = Field(default=None, max_length=280)
