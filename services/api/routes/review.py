"""Unified Review Center read adapter (#256).

This deliberately does not duplicate or mutate source records. It combines
the existing incident, event, and household-notification streams into the
single queue the UI can use today. Identity/relationship producers will plug
into the same response contract in later slices.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import ALL, allowed_camera_ids, apply_camera_filter
from shared.database import get_db
from shared.models import (
    AssociationEvidence,
    BodyCluster,
    Camera,
    EntityAssociation,
    Event,
    FaceCluster,
    Incident,
    Notification,
    User,
)
from shared.schemas import ReviewItemResponse, ReviewQueueResponse

router = APIRouter()

_KINDS = {"incident", "alert", "notification", "identity_suggestion", "relationship_suggestion", "camera_health", "privacy_review"}


class RelationshipDecisionBody(BaseModel):
    decision: Literal["confirm", "reject", "defer"]
    note: str | None = Field(default=None, max_length=1000)


def _association_visible(association: EntityAssociation, allowed) -> bool:
    if allowed is ALL:
        return True
    allowed_ids = {str(camera_id) for camera_id in allowed}
    return bool(allowed_ids.intersection(str(camera_id) for camera_id in (association.camera_histogram or {})))


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

    if "identity_suggestion" in requested:
        face_query = apply_camera_filter(
            select(FaceCluster)
            .where(FaceCluster.status == "pending")
            .order_by(FaceCluster.last_seen_at.desc()),
            allowed,
            FaceCluster.first_camera_id,
        )
        for cluster in (await db.execute(face_query.limit(100))).scalars().all():
            items.append(_item(
                source_type="face_cluster",
                source_id=cluster.id,
                kind="identity_suggestion",
                status="open",
                priority="normal",
                title="Unknown person needs review",
                summary=(
                    f"{cluster.sighting_count} sightings of "
                    f"{cluster.auto_label_number and f'Unknown {cluster.auto_label_number}' or 'the same unknown person'}"
                ),
                created_at=cluster.created_at,
                updated_at=cluster.last_seen_at,
                camera_id=cluster.first_camera_id,
                unread=True,
                evidence={
                    "sample_thumbnail_path": cluster.sample_thumbnail_path,
                    "sighting_count": cluster.sighting_count,
                    "first_seen_at": cluster.first_seen_at,
                    "last_seen_at": cluster.last_seen_at,
                    "appearance_description": cluster.appearance_description,
                },
                provenance={"source": "face_cluster", "cluster_status": cluster.status},
            ))

        body_query = apply_camera_filter(
            select(BodyCluster)
            .where(BodyCluster.status == "pending")
            .order_by(BodyCluster.last_seen_at.desc()),
            allowed,
            BodyCluster.first_camera_id,
        )
        for cluster in (await db.execute(body_query.limit(100))).scalars().all():
            items.append(_item(
                source_type="body_cluster",
                source_id=cluster.id,
                kind="identity_suggestion",
                status="open",
                priority="normal",
                title="Unknown appearance needs review",
                summary=f"{cluster.sighting_count} sightings of a recurring body appearance",
                created_at=cluster.created_at,
                updated_at=cluster.last_seen_at,
                camera_id=cluster.first_camera_id,
                unread=True,
                evidence={
                    "sample_thumbnail_path": cluster.sample_thumbnail_path,
                    "sighting_count": cluster.sighting_count,
                    "first_seen_at": cluster.first_seen_at,
                    "last_seen_at": cluster.last_seen_at,
                    "appearance_description": cluster.appearance_description,
                },
                provenance={"source": "body_cluster", "cluster_status": cluster.status},
            ))

    if "relationship_suggestion" in requested:
        association_rows = (
            await db.execute(
                select(EntityAssociation)
                .where(EntityAssociation.status == "candidate")
                .order_by(EntityAssociation.last_seen_at.desc())
                .limit(100)
            )
        ).scalars().all()
        for association in association_rows:
            # A restricted user may only see an association if at least one
            # supporting camera is in scope. Do not leak the existence of an
            # otherwise hidden relationship through queue counts.
            if not _association_visible(association, allowed):
                continue
            relation = association.relation.replace("_", " ")
            items.append(_item(
                source_type="association",
                source_id=association.id,
                kind="relationship_suggestion",
                status="open",
                priority="normal",
                title="Possible relationship needs review",
                summary=(
                    f"{association.subject_key} is often seen {relation} "
                    f"{association.object_label or association.object_key}"
                ),
                created_at=association.created_at,
                updated_at=association.last_seen_at or association.created_at,
                camera_id=None,
                unread=True,
                evidence={
                    "evidence_count": association.evidence_count,
                    "distinct_days": association.distinct_days,
                    "first_seen_at": association.first_seen_at,
                    "last_seen_at": association.last_seen_at,
                    "camera_histogram": association.camera_histogram or {},
                },
                provenance={"source": association.source, "relation": association.relation},
            ))

    if unread_only:
        items = [item for item in items if item.unread]
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


@router.get("/associations")
async def list_entity_associations(
    subject_kind: str | None = Query(default=None),
    subject_key: str | None = Query(default=None),
    object_kind: str | None = Query(default=None),
    object_key: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the same association projections used by entity detail pages.

    Review remains the only decision surface; this endpoint is read-only and
    exists so People, Vehicles, and future cluster views can show context
    without duplicating inference or lifecycle rules.
    """
    if not any((subject_key, object_key)):
        raise HTTPException(status_code=422, detail="subject_key or object_key is required")
    allowed = await allowed_camera_ids(current_user, db)
    query = select(EntityAssociation).where(EntityAssociation.status != "rejected")
    if subject_kind and subject_key and not object_key:
        query = query.where(or_(
            and_(EntityAssociation.subject_kind == subject_kind, EntityAssociation.subject_key == subject_key),
            and_(EntityAssociation.object_kind == subject_kind, EntityAssociation.object_key == subject_key),
        ))
    else:
        if subject_kind:
            query = query.where(EntityAssociation.subject_kind == subject_kind)
        if subject_key:
            query = query.where(EntityAssociation.subject_key == subject_key)
    if object_kind:
        query = query.where(EntityAssociation.object_kind == object_kind)
    if object_key:
        query = query.where(EntityAssociation.object_key == object_key)
    rows = (
        await db.execute(query.order_by(EntityAssociation.last_seen_at.desc()).limit(100))
    ).scalars().all()
    result = []
    for row in rows:
        viewed_as_subject = row.subject_kind == subject_kind and row.subject_key == subject_key
        result.append({
            "id": str(row.id),
            "subject_kind": row.subject_kind,
            "subject_key": row.subject_key,
            "object_kind": row.object_kind,
            "object_key": row.object_key,
            "object_label": row.object_label,
            "relation": row.relation,
            "status": row.status,
            "source": row.source,
            "user_confirmed": row.user_confirmed,
            "evidence_count": row.evidence_count,
            "distinct_days": row.distinct_days,
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
            "counterpart_label": (
                row.object_label or row.object_key if viewed_as_subject else row.subject_key
            ),
            "evidence_url": f"/api/review/relationship-suggestions/{row.id}",
        })
    return [item for row, item in zip(rows, result) if _association_visible(row, allowed)]


@router.post("/relationship-suggestions/{association_id}/decision")
async def decide_relationship_suggestion(
    association_id: uuid.UUID,
    body: RelationshipDecisionBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm or reject a learned relationship without exposing hidden evidence.

    Decisions are intentionally irreversible through this endpoint: rejected
    associations must not be silently revived by later inference, and an
    established edge must be changed through a future explicit relationship
    editor rather than by replaying a notification action.
    """
    association = await db.get(EntityAssociation, association_id)
    if not association or association.status not in {"candidate", "deferred"}:
        raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL:
        allowed_ids = {str(camera_id) for camera_id in allowed}
        if not any(str(camera_id) in allowed_ids for camera_id in (association.camera_histogram or {})):
            raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    association.status = {
        "confirm": "established",
        "reject": "rejected",
        "defer": "deferred",
    }[body.decision]
    association.user_confirmed = body.decision == "confirm"
    association.reviewed_at = datetime.now(timezone.utc)
    association.reviewed_by_user_id = current_user.id
    association.review_note = body.note.strip() if body.note else None
    await db.commit()
    return {
        "id": str(association.id),
        "status": association.status,
        "user_confirmed": association.user_confirmed,
        "reviewed_at": association.reviewed_at,
    }


@router.get("/relationship-suggestions/{association_id}")
async def get_relationship_suggestion(
    association_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a relationship hypothesis and only its visible evidence episodes."""
    association = await db.get(EntityAssociation, association_id)
    if not association:
        raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    allowed = await allowed_camera_ids(current_user, db)
    allowed_ids = {str(camera_id) for camera_id in allowed} if allowed is not ALL else None
    association_cameras = {str(camera_id) for camera_id in (association.camera_histogram or {})}
    if allowed_ids is not None and not association_cameras.intersection(allowed_ids):
        raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    rows = (
        await db.execute(
            select(AssociationEvidence)
            .where(AssociationEvidence.association_id == association.id)
            .order_by(AssociationEvidence.observed_at.desc())
        )
    ).scalars().all()
    evidence = []
    for row in rows:
        cameras = {str(camera_id) for camera_id in (row.camera_ids or [])}
        if allowed_ids is not None and not cameras.intersection(allowed_ids):
            continue
        evidence.append({
            "id": str(row.id),
            "episode_key": row.episode_key,
            "kind": row.evidence_kind,
            "role": row.role,
            "journey_id": str(row.journey_id) if row.journey_id else None,
            "observation_ids": row.observation_ids or [],
            "camera_ids": row.camera_ids or [],
            "observed_at": row.observed_at,
            "score": row.score,
            "explanation": row.explanation,
            "metadata": row.evidence_metadata or {},
        })
    return {
        "id": str(association.id),
        "subject_kind": association.subject_kind,
        "subject_key": association.subject_key,
        "object_kind": association.object_kind,
        "object_key": association.object_key,
        "object_label": association.object_label,
        "relation": association.relation,
        "source": association.source,
        "status": association.status,
        "user_confirmed": association.user_confirmed,
        "evidence_count": association.evidence_count,
        "distinct_days": association.distinct_days,
        "first_seen_at": association.first_seen_at,
        "last_seen_at": association.last_seen_at,
        "evidence": evidence,
    }
