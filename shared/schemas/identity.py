"""People, face clusters and cluster naming: anyone Nurby
recognises or a household has named.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


# ── Person schemas ──

class PersonCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    nickname: str | None = Field(default=None, max_length=255)
    relationship: str | None = Field(default=None, max_length=64)
    consent_given: bool = False
    privacy_blur: bool = False
    is_starred: bool = False
    recap_prompt: str | None = Field(default=None, max_length=2000)
    recap_provider: str | None = Field(default=None, max_length=32)
    recap_model: str | None = Field(default=None, max_length=255)


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    nickname: str | None = Field(default=None, max_length=255)
    relationship: str | None = Field(default=None, max_length=64)
    consent_given: bool | None = None
    privacy_blur: bool | None = None
    is_starred: bool | None = None
    recap_prompt: str | None = Field(default=None, max_length=2000)
    recap_provider: str | None = Field(default=None, max_length=32)
    recap_model: str | None = Field(default=None, max_length=255)


class PersonResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    nickname: str | None
    relationship: str | None
    consent_given: bool
    privacy_blur: bool
    photo_path: str | None
    is_starred: bool
    recap_prompt: str | None
    recap_provider: str | None
    recap_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonRecapResponse(BaseModel):
    person_id: uuid.UUID
    display_name: str
    photo_path: str | None
    status: str
    last_seen_at: datetime | None
    last_camera_id: uuid.UUID | None
    last_camera_name: str | None
    last_thumbnail_path: str | None
    last_observation_id: uuid.UUID | None = None
    sightings_24h: int
    generated_at: datetime
    cached: bool
    stale: bool


# ── Face cluster schemas ──

class FaceClusterResponse(BaseModel):
    id: uuid.UUID
    sample_thumbnail_path: str | None
    sighting_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    first_camera_id: uuid.UUID | None
    person_id: uuid.UUID | None
    status: str

    model_config = {"from_attributes": True}


class FaceClusterSampleResponse(BaseModel):
    id: uuid.UUID
    cluster_id: uuid.UUID
    camera_id: uuid.UUID
    thumbnail_path: str | None
    captured_at: datetime

    model_config = {"from_attributes": True}


class NameClusterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    relationship: str | None = Field(default=None, max_length=64)
