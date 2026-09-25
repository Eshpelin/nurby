"""The common Review Center response contract.

The first implementation is a read adapter over existing incidents, events,
and notifications. Keeping this contract independent of those source tables
lets the UI converge on one queue without creating a second source of truth.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ReviewKind = Literal[
    "incident",
    "alert",
    "notification",
    "identity_suggestion",
    "relationship_suggestion",
    "camera_health",
    "privacy_review",
]


class ReviewItemResponse(BaseModel):
    id: str = Field(description="Stable review id: <source_type>:<source_id>")
    kind: ReviewKind
    status: str
    priority: str
    title: str
    summary: str
    created_at: datetime
    updated_at: datetime
    source_type: str
    source_id: uuid.UUID
    camera_id: uuid.UUID | None = None
    camera_name: str | None = None
    unread: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ReviewQueueResponse(BaseModel):
    items: list[ReviewItemResponse]
    limit: int
    offset: int
    next_offset: int | None = None
    total: int
