"""Guardian links, facilities, approved pickups, alert
preferences and the guardian access log.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Guardian by Nurby schemas ──

class FacilityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    timezone: str | None = Field(default=None, max_length=64)
    reveal_min_confidence: float | None = Field(default=None, ge=0.5, le=1.0)
    max_cameras_per_person: int | None = Field(default=None, ge=1, le=1000)


class FacilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    reveal_min_confidence: float | None = Field(default=None, ge=0.5, le=1.0)
    max_cameras_per_person: int | None = Field(default=None, ge=1, le=1000)


class FacilityResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str | None
    is_default: bool
    reveal_min_confidence: float | None
    max_cameras_per_person: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class GuardianLinkCreate(BaseModel):
    # Bind an existing guardian user (by id or email) to an existing person.
    person_id: uuid.UUID
    guardian_user_id: uuid.UUID | None = None
    guardian_email: str | None = Field(default=None, max_length=255)
    facility_id: uuid.UUID | None = None  # defaults to the default facility
    relationship_label: str | None = Field(default=None, max_length=64)
    tier: str = Field(default="full", pattern=r"^(full|summary|alerts_only)$")
    alert_prefs: dict | None = None
    premium: bool = False
    live_presence: bool = False
    live_video: bool = False
    audio: bool = False
    is_primary_parent: bool = False
    reveal_min_confidence: float | None = Field(default=None, ge=0.5, le=1.0)
    expires_at: datetime | None = None


class GuardianLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship_label: str | None = Field(default=None, max_length=64)
    tier: str | None = Field(default=None, pattern=r"^(full|summary|alerts_only)$")
    alert_prefs: dict | None = None
    premium: bool | None = None
    live_presence: bool | None = None
    live_video: bool | None = None
    audio: bool | None = None
    is_primary_parent: bool | None = None
    reveal_min_confidence: float | None = Field(default=None, ge=0.5, le=1.0)
    expires_at: datetime | None = None


class GuardianAlertPrefsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_prefs: dict


class GuardianChannelsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notify_channels: dict


class GuardianLinkResponse(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    person_id: uuid.UUID
    guardian_user_id: uuid.UUID
    relationship_label: str | None
    tier: str
    alert_prefs: dict | None
    notify_channels: dict | None
    premium: bool
    live_presence: bool
    live_video: bool
    audio: bool
    is_primary_parent: bool
    reveal_min_confidence: float | None
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    model_config = {"from_attributes": True}


class ApprovedPickupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="person", pattern=r"^(person|vehicle)$")
    linked_person_id: uuid.UUID | None = None
    vehicle_plate: str | None = Field(default=None, max_length=32)


class ApprovedPickupResponse(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    name: str
    kind: str
    linked_person_id: uuid.UUID | None
    vehicle_plate: str | None
    photo_path: str | None
    active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class HandoverConfirmRequest(BaseModel):
    """An authorized staff decision on an inferred pickup event.

    ``decision`` is ``confirmed`` (an authorized guardian did take custody) or
    ``corrected`` (review found this was not a valid handover). Nothing here
    auto-confirms; the endpoint requires an admin and records who and when.
    """

    decision: str = Field(pattern=r"^(confirmed|corrected)$")
    note: str | None = Field(default=None, max_length=1000)
    evidence: dict | None = None


class HandoverConfirmationResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    decision: str
    prior_state: str | None
    confirmed_by_user_id: uuid.UUID | None
    evidence: dict | None
    note: str | None
    at: datetime
    model_config = ConfigDict(from_attributes=True)


class GuardianHandoverResponse(BaseModel):
    """Current evidence state of a pickup event plus its full decision trail."""

    event_id: uuid.UUID
    kind: str
    handover_state: str
    handover_state_label: str
    staff_confirmed: bool
    pickup_matched: bool | None
    pickup_name: str | None
    message: str
    history: list[HandoverConfirmationResponse]


class GuardianAccessLogResponse(BaseModel):
    id: uuid.UUID
    guardian_link_id: uuid.UUID
    guardian_user_id: uuid.UUID
    person_id: uuid.UUID
    action: str
    at: datetime
    ip: str | None
    detail: dict | None
    model_config = {"from_attributes": True}
