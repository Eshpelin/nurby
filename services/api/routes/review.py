"""Unified Review Center read adapter (#256).

This deliberately does not duplicate or mutate source records. It combines
the existing incident, event, and household-notification streams into the
single queue the UI can use today. Identity/relationship producers will plug
into the same response contract in later slices.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import allowed_camera_ids, apply_camera_filter
from shared.database import get_db
from shared.models import Camera, Event, Incident, Notification, User
from shared.schemas import ReviewItemResponse, ReviewQueueResponse

router = APIRouter()

_KINDS = {"incident", "alert", "notification", "identity_suggestion", "relationship_suggestion", "camera_health", "privacy_review"}


def _review_visible(camera_id):
    """Match the existing Events review policy for excluded cameras."""
    excluded = select(Camera.id).where(Camera.exclude_from_review.is_(True))
    return or_(camera_id.is_(None), camera_id.not_in(excluded))


def _as_utc(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _item(
    *,
    source_type: str,
    source_id: uuid.UUID,
    kind: str,
    status: str,
    priority: str,
    title: str,
    summary: str,
    created_at: datetime | None,
    updated_at: datetime | None,
    camera_id: uuid.UUID | None,
    unread: bool,
    evidence: dict | None = None,
    provenance: dict | None = None,
) -> ReviewItemResponse:
    return ReviewItemResponse(
        id=f"{source_type}:{source_id}",
        kind=kind,  # validated by Pydantic; producers cannot invent kinds
        status=status,
        priority=priority,
        title=title,
        summary=summary,
        created_at=_as_utc(created_at),
        updated_at=_as_utc(updated_at or created_at),
        source_type=source_type,
        source_id=source_id,
        camera_id=camera_id,
        unread=unread,
        evidence=evidence or {},
        provenance=provenance or {},
    )


async def _camera_names(db: AsyncSession, camera_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = list(set(camera_ids))
    if not ids:
        return {}
    rows = (await db.execute(select(Camera.id, Camera.name).where(Camera.id.in_(ids)))).all()
    return {camera_id: name for camera_id, name in rows}


@router.get("", response_model=ReviewQueueResponse)
async def list_review_items(
    kind: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one permission-scoped queue over existing reviewable sources.

    This read adapter intentionally uses offset pagination for the first slice;
    the materialized ReviewItem table and cursor contract come after the UI
    proves the merged workflow. The public response shape will remain stable.
    """
    requested = {part.strip() for part in kind.split(",")} if kind else _KINDS
    invalid = requested - _KINDS
    if invalid:
        raise HTTPException(status_code=422, detail=f"unknown review kind: {sorted(invalid)[0]}")
    requested &= _KINDS
    allowed = await allowed_camera_ids(current_user, db)
    items: list[ReviewItemResponse] = []

    if "incident" in requested:
        query = apply_camera_filter(
            select(Incident).where(_review_visible(Incident.camera_id)).order_by(Incident.last_seen_at.desc()),
            allowed,
            Incident.camera_id,
        )
        incidents = (await db.execute(query.limit(250))).scalars().all()
        for incident in incidents:
            status = getattr(incident, "status", "open")
            items.append(_item(
                source_type="incident",
                source_id=incident.id,
                kind="incident",
                status="rejected" if status == "dismissed" else status,
                priority="high" if status == "open" else "normal",
                title="Incident needs review" if status == "open" else "Incident",
                summary=incident.summary_text or f"{incident.occurrence_count} related sightings",
                created_at=incident.created_at,
                updated_at=incident.last_seen_at,
                camera_id=incident.camera_id,
                unread=status == "open",
                evidence={
                    "occurrence_count": incident.occurrence_count,
                    "first_seen_at": incident.started_at,
                    "last_seen_at": incident.last_seen_at,
                    "peak_observation_id": incident.peak_observation_id,
                },
                provenance={"source": "incident_tracker"},
            ))

    if "alert" in requested or "camera_health" in requested:
        query = apply_camera_filter(
            select(Event).where(_review_visible(Event.camera_id)).order_by(Event.fired_at.desc()),
            allowed,
            Event.camera_id,
        )
        events = (await db.execute(query.limit(250))).scalars().all()
        for event in events:
            is_health = (event.payload or {}).get("event_kind") == "camera_status"
            event_kind = "camera_health" if is_health else "alert"
            if event_kind not in requested:
                continue
            acknowledged = bool(event.acked_at or event.acknowledged_at)
            items.append(_item(
                source_type="event",
                source_id=event.id,
                kind=event_kind,
                status="resolved" if acknowledged else "open",
                priority="high" if event.severity == "alert" else "normal",
                title="Camera health alert" if is_health else "Alert needs review",
                summary=(event.payload or {}).get("reason") or "A rule fired and needs review",
                created_at=event.fired_at,
                updated_at=event.fired_at,
                camera_id=event.camera_id,
                unread=not acknowledged,
                evidence={"payload": event.payload or {}},
                provenance={"source": "rule_engine", "rule_id": event.rule_id},
            ))

    if "notification" in requested:
        query = apply_camera_filter(
            select(Notification).where(_review_visible(Notification.camera_id)).order_by(Notification.created_at.desc()),
            allowed,
            Notification.camera_id,
        )
        notifications = (await db.execute(query.limit(250))).scalars().all()
        for notification in notifications:
            items.append(_item(
                source_type="notification",
                source_id=notification.id,
                kind="notification",
                status="open" if not notification.read else "resolved",
                priority="high" if notification.severity == "critical" else "normal",
                title="Notification",
                summary=notification.message,
                created_at=notification.created_at,
                updated_at=notification.created_at,
                camera_id=notification.camera_id,
                unread=not notification.read,
                evidence={"observation_id": notification.observation_id},
                provenance={"source": "notification", "rule_id": notification.rule_id},
            ))

    items.sort(key=lambda item: item.updated_at, reverse=True)
    total = len(items)
    page = items[offset:offset + limit]
    return ReviewQueueResponse(
        items=page,
        limit=limit,
        offset=offset,
        next_offset=offset + limit if offset + limit < total else None,
        total=total,
    )
