"""Observations, notifications, events and the notes a
household attaches to an event.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Observation schemas ──

class ObservationResponse(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    object_detections: dict | None
    person_detections: dict | None
    vlm_description: str | None
    vlm_provider: str | None
    confidence: float | None
    thumbnail_path: str | None
    clip_path: str | None
    primary_vlm_description: str | None = None
    refined_by_provider_name: str | None = None
    refined_at: datetime | None = None
    incident_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


# ── Notification schemas ──

class NotificationResponse(BaseModel):
    id: uuid.UUID
    message: str
    severity: str
    rule_id: uuid.UUID | None
    camera_id: uuid.UUID | None
    observation_id: uuid.UUID | None
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Event schemas ──

class EventResponse(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    observation_id: uuid.UUID | None
    recording_id: uuid.UUID | None = None
    fired_at: datetime
    payload: dict | None
    acknowledged_at: datetime | None
    action_status: str
    action_error: str | None
    action_type: str | None
    # Phase 2 ack fields. ``acked_via`` is one of ``telegram``,
    # ``web``, ``api`` (or null if not yet acknowledged).
    acked_at: datetime | None = None
    acked_by_user_id: uuid.UUID | None = None
    acked_via: str | None = None
    muted_until: datetime | None = None

    model_config = {"from_attributes": True}


class EventNoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class EventNoteResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    author_user_id: uuid.UUID | None = None
    author_display_name: str | None = None
    source: str  # telegram | web | api
    text: str
    telegram_message_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Alert feedback (#195) ──

class EventFeedbackCreate(BaseModel):
    """Two interactions: pick a rating, optionally pick one reason. A
    reason applies only to incorrect alerts; anything else re-runs as a
    correction by submitting a new rating for the same event."""

    rating: Literal["useful", "correct_but_not_useful", "incorrect"]
    reason: Literal["wrong_object", "wrong_person", "duplicate", "timing"] | None = None

    @model_validator(mode="after")
    def reason_only_for_incorrect(self):
        if self.reason is not None and self.rating != "incorrect":
            raise ValueError("reason applies only to incorrect alerts")
        return self


class EventFeedbackResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID | None = None
    reviewer_display_name: str | None = None
    rating: str
    reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
