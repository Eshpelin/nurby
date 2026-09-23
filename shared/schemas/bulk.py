"""Request/response contracts for bounded bulk media and event operations."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RecordingSelectionFilters(BaseModel):
    camera_id: uuid.UUID | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    objects: list[str] = Field(default_factory=list)
    person_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None

    model_config = {"populate_by_name": True}


class EventSelectionFilters(BaseModel):
    camera_id: uuid.UUID | None = None
    rule_id: uuid.UUID | None = None
    status: str | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    person_id: uuid.UUID | None = None
    label: str | None = None
    acked: bool | None = None
    severity: str | None = None

    model_config = {"populate_by_name": True}


class BulkSelectionRequest(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    all_matching: bool = False
    # Kept as a mapping because recording and event filters intentionally have
    # different fields. The resource endpoint validates it against its own
    # filter model; a union here would silently accept one as the other.
    filters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_selection(self):
        if not self.ids and not self.all_matching:
            raise ValueError("select at least one id or set all_matching")
        if self.ids and self.all_matching:
            raise ValueError("ids and all_matching are mutually exclusive")
        return self


class BulkPreviewResponse(BaseModel):
    resource: str
    requested: int
    matching: int
    estimated_bytes: int = 0
    cameras: list[uuid.UUID] = Field(default_factory=list)
    missing_files: int = 0
    linked_recordings: int = 0


class BulkDeleteResponse(BaseModel):
    resource: str
    requested: int
    deleted: int
    missing: int = 0
    skipped: int = 0
    failed: int = 0
    failed_ids: list[uuid.UUID] = Field(default_factory=list)
