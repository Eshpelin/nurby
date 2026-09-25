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
    AssociationReviewEvent,
    BodyCluster,
    Camera,
    EntityAssociation,
    Event,
    FaceCluster,
    Incident,
    Notification,
    Transcript,
    User,
)
from shared.schemas import ReviewItemResponse, ReviewQueueResponse

router = APIRouter()

_KINDS = {"incident", "alert", "notification", "identity_suggestion", "relationship_suggestion", "camera_health", "privacy_review"}


class RelationshipDecisionBody(BaseModel):
    decision: Literal["confirm", "reject", "defer", "revoke", "restore"]
    note: str | None = Field(default=None, max_length=1000)
    # Clients may send the review timestamp they saw.  This prevents an old
    # open tab from overwriting a newer review while preserving retry-safe
    # behavior when the same decision is submitted again.
    expected_reviewed_at: datetime | None = None


def _association_visible(association: EntityAssociation, allowed) -> bool:
    if allowed is ALL:
        return True
    allowed_ids = {str(camera_id) for camera_id in allowed}
    return bool(allowed_ids.intersection(str(camera_id) for camera_id in (association.camera_histogram or {})))


def _scoped_evidence(row: AssociationEvidence, allowed_ids: set[str] | None) -> dict | None:
    """Project one evidence episode without leaking restricted camera sources.

    An episode may contain observations from more than one camera.  We cannot
    safely expose observation ids or a journey URL for a mixed episode unless
    every contributing camera is visible to the caller, so those source
    pointers are redacted while the permitted camera names/ids remain useful.
    """
    cameras = {str(camera_id) for camera_id in (row.camera_ids or [])}
    if allowed_ids is not None:
        visible_cameras = cameras.intersection(allowed_ids)
        if cameras and not visible_cameras:
            return None
        fully_visible = not cameras or cameras <= allowed_ids
        camera_ids = sorted(visible_cameras)
    else:
        fully_visible = True
        camera_ids = sorted(cameras)
    metadata = dict(row.evidence_metadata or {})
    transcript_id = metadata.get("transcript_id")
    if not fully_visible:
        # A mixed episode must not carry a hidden transcript/source identifier
        # in an otherwise harmless metadata payload.
        metadata.pop("transcript_id", None)
    return {
        "id": str(row.id),
        "episode_key": row.episode_key,
        "kind": row.evidence_kind,
        "role": row.role,
        "journey_id": str(row.journey_id) if row.journey_id and fully_visible else None,
        "observation_ids": (row.observation_ids or []) if fully_visible else [],
        "camera_ids": camera_ids,
        "observed_at": row.observed_at,
        "score": row.score,
        "explanation": row.explanation,
        "metadata": metadata,
        "fully_visible": fully_visible,
        "transcript_id": transcript_id if fully_visible else None,
    }


def _review_visible(camera_id):
    """Match the existing Events review policy for excluded cameras."""
    excluded = select(Camera.id).where(Camera.exclude_from_review.is_(True))
    return or_(camera_id.is_(None), camera_id.not_in(excluded))


def _as_utc(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _incident_review_reason(
    incident: Incident,
    fired_incident_ids: set[str],
    review_all_open: bool = False,
) -> tuple[bool, str]:
    """Return whether an incident deserves the red review treatment.

    Incident tracking is useful history, so an open row is not automatically
    an actionable task. Rules and explicit unknown-subject signals are the
    two product reasons that should interrupt a household.
    """
    if review_all_open and incident.status == "open":
        return True, "Open incident in the assigned-workflow mode"
    if str(incident.id) in fired_incident_ids:
        return True, "A rule fired for this incident"
    if incident.signature_kind in {"unknown", "body", "cluster"}:
        return True, f"Unknown subject seen {incident.occurrence_count} times"
    return False, "Recorded camera activity"


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
        # Event payloads retain the incident link without adding another
        # relationship table. Keep this set permission-scoped by camera.
        event_query = apply_camera_filter(
            select(Event).where(_review_visible(Event.camera_id)),
            allowed,
            Event.camera_id,
        )
        fired_incident_ids = {
            str((event.payload or {}).get("incident_id"))
            for event in (await db.execute(event_query.limit(1000))).scalars().all()
            if (event.payload or {}).get("incident_id")
        }
        review_all_open = (await db.execute(
            select(Incident.id)
            .where(Incident.assigned_to_user_id.is_not(None))
            .limit(1)
        )).scalar_one_or_none() is not None
        query = apply_camera_filter(
            select(Incident).where(_review_visible(Incident.camera_id)).order_by(Incident.last_seen_at.desc()),
            allowed,
            Incident.camera_id,
        )
        incidents = (await db.execute(query.limit(250))).scalars().all()
        for incident in incidents:
            status = getattr(incident, "status", "open")
            needs_review, reason = _incident_review_reason(
                incident, fired_incident_ids, review_all_open
            )
            actionable = status == "open" and needs_review
            items.append(_item(
                source_type="incident",
                source_id=incident.id,
                kind="incident",
                status="rejected" if status == "dismissed" else status,
                priority="high" if actionable else "normal",
                title="Incident needs review" if actionable else "Incident history",
                summary=f"{reason}. {incident.summary_text or f'{incident.occurrence_count} related sightings'}",
                created_at=incident.created_at,
                updated_at=incident.last_seen_at,
                camera_id=incident.camera_id,
                unread=actionable,
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
                created_at=cluster.first_seen_at,
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
                created_at=cluster.first_seen_at,
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

    if "relationship_suggestion" in requested or "identity_suggestion" in requested:
        association_rows = (
            await db.execute(
                select(EntityAssociation)
                .where(EntityAssociation.status.in_(["candidate", "ambiguous", "deferred"]))
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
            association_kind = (
                "identity_suggestion"
                if association.relation == "possibly_named"
                else "relationship_suggestion"
            )
            if association_kind not in requested:
                continue
            relation = association.relation.replace("_", " ")
            items.append(_item(
                source_type="association",
                source_id=association.id,
                kind=association_kind,
                status=association.status,
                priority="normal",
                title=("Possible name from audio" if association_kind == "identity_suggestion"
                       else "Conflicting relationship needs review" if association.status == "ambiguous"
                       else "Possible relationship needs review"),
                summary=(
                    f"{association.subject_key} may be {association.object_label or association.object_key}"
                    if association_kind == "identity_suggestion"
                    else f"{association.subject_key} is often seen {relation} "
                         f"{association.object_label or association.object_key}"
                ),
                created_at=association.created_at,
                updated_at=association.last_seen_at or association.created_at,
                camera_id=None,
                unread=True,
                evidence={
                    "evidence_count": association.evidence_count,
                    "supporting_evidence_count": getattr(association, "supporting_evidence_count", association.evidence_count),
                    "contradictory_evidence_count": getattr(association, "contradictory_evidence_count", 0),
                    "confidence_score": association.confidence_score,
                    "decision_explanation": association.decision_explanation,
                    "distinct_days": association.distinct_days,
                    "first_seen_at": association.first_seen_at,
                    "last_seen_at": association.last_seen_at,
                    "camera_histogram": association.camera_histogram or {},
                },
                provenance={"source": association.source, "relation": association.relation},
            ))

    if unread_only:
        items = [item for item in items if item.unread]
    camera_names = await _camera_names(db, (item.camera_id for item in items if item.camera_id))
    for item in items:
        if item.camera_id:
            item.camera_name = camera_names.get(item.camera_id)
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
    status: str | None = Query(default=None),
    camera_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
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
    if status:
        query = query.where(EntityAssociation.status == status)
    # Scope before applying offset/limit.  The histogram is an aggregate of
    # visible source cameras, so a restricted caller must never page through
    # hidden rows and infer their existence from a short page.
    candidates = (await db.execute(query.order_by(EntityAssociation.last_seen_at.desc()).limit(1000))).scalars().all()
    rows = [
        row for row in candidates
        if _association_visible(row, allowed)
        and (camera_id is None or str(camera_id) in {str(value) for value in (row.camera_histogram or {})})
    ][offset:offset + limit]
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
            "supporting_evidence_count": getattr(row, "supporting_evidence_count", row.evidence_count),
            "contradictory_evidence_count": getattr(row, "contradictory_evidence_count", 0),
            "confidence_score": row.confidence_score,
            "decision_explanation": row.decision_explanation,
            "distinct_days": row.distinct_days,
            "first_seen_at": row.first_seen_at,
            "last_seen_at": row.last_seen_at,
            "counterpart_label": (
                row.object_label or row.object_key if viewed_as_subject else row.subject_key
            ),
            "evidence_url": f"/api/review/relationship-suggestions/{row.id}",
        })
    return result


@router.post("/relationship-suggestions/{association_id}/decision")
async def decide_relationship_suggestion(
    association_id: uuid.UUID,
    body: RelationshipDecisionBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply an audited review decision without exposing hidden evidence.

    Revoke is reversible: it archives a confirmed relationship while keeping
    its evidence and decision history. Restore returns it to candidate review
    rather than silently re-confirming it. Reject remains terminal for learned
    inference and cannot be undone by this endpoint.
    """
    # Serialize decisions for this edge.  Without the row lock two reviewers
    # can both observe a candidate, append conflicting audit events, and let
    # the last commit silently win.
    association = (
        await db.execute(
            select(EntityAssociation)
            .where(EntityAssociation.id == association_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        association is not None
        and body.expected_reviewed_at is not None
        and association.reviewed_at != body.expected_reviewed_at
    ):
        raise HTTPException(
            status_code=409,
            detail="Relationship was reviewed after this page loaded; refresh before deciding again.",
        )
    valid_status = (
        association is not None
        and (
            association.status in {"candidate", "ambiguous", "deferred"}
            or body.decision == "confirm" and association.status == "established" and association.user_confirmed
            or body.decision == "reject" and association.status == "rejected"
            or body.decision == "defer" and association.status == "deferred"
            or body.decision == "revoke" and association.status == "established"
            or body.decision == "restore" and association.status == "archived"
            or body.decision == "revoke" and association.status == "archived" and association.archived_at is not None
            or body.decision == "restore" and association.status == "candidate" and association.archived_at is None
        )
    )
    if not valid_status:
        raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL:
        allowed_ids = {str(camera_id) for camera_id in allowed}
        if not any(str(camera_id) in allowed_ids for camera_id in (association.camera_histogram or {})):
            raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    already_applied = (
        body.decision == "confirm" and association.status == "established" and association.user_confirmed
        or body.decision == "reject" and association.status == "rejected"
        or body.decision == "defer" and association.status == "deferred"
        or body.decision == "revoke" and association.status == "archived" and association.archived_at is not None
        or body.decision == "restore" and association.status == "candidate" and association.archived_at is None
    )
    if already_applied:
        return {
            "id": str(association.id),
            "status": association.status,
            "user_confirmed": association.user_confirmed,
            "reviewed_at": association.reviewed_at,
            "archived_at": association.archived_at,
            "idempotent": True,
        }

    old_status = association.status
    association.status = {
        "confirm": "established",
        "reject": "rejected",
        "defer": "deferred",
        "revoke": "archived",
        "restore": "candidate",
    }[body.decision]
    association.user_confirmed = body.decision == "confirm"
    if body.decision == "revoke":
        association.archived_at = datetime.now(timezone.utc)
    elif body.decision == "restore":
        association.archived_at = None
    association.reviewed_at = datetime.now(timezone.utc)
    association.reviewed_by_user_id = current_user.id
    association.review_note = body.note.strip() if body.note else None
    db.add(AssociationReviewEvent(
        association_id=association.id,
        reviewer_user_id=current_user.id,
        action=body.decision,
        old_status=old_status,
        new_status=association.status,
        note=association.review_note,
    ))
    await db.commit()
    return {
        "id": str(association.id),
        "status": association.status,
        "user_confirmed": association.user_confirmed,
        "reviewed_at": association.reviewed_at,
        "archived_at": association.archived_at,
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
        scoped = _scoped_evidence(row, allowed_ids)
        if scoped is None:
            continue
        metadata = scoped["metadata"]
        transcript_id = scoped["transcript_id"]
        transcript_exists = True
        transcript_edited = False
        if transcript_id:
            try:
                transcript = await db.scalar(
                    select(Transcript).where(Transcript.id == uuid.UUID(str(transcript_id)))
                )
                transcript_exists = transcript is not None
                transcript_edited = bool(transcript and transcript.text_edited)
            except (TypeError, ValueError):
                transcript_exists = False
        if transcript_id and not transcript_exists:
            source_status = "source_expired"
        elif transcript_id and transcript_edited:
            source_status = "source_changed"
        else:
            source_status = "available" if row.observation_ids or row.journey_id or transcript_id else "source_expired"
        evidence.append({
            **scoped,
            "source_status": source_status,
            "source_url": (
                f"/api/transcripts/{transcript_id}" if transcript_id and transcript_exists
                else f"/api/journeys/{row.journey_id}" if row.journey_id and scoped["fully_visible"]
                else None
            ),
        })
    review_events = (
        await db.execute(
            select(AssociationReviewEvent)
            .where(AssociationReviewEvent.association_id == association.id)
            .order_by(AssociationReviewEvent.created_at.desc())
        )
    ).scalars().all()
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
        "supporting_evidence_count": getattr(association, "supporting_evidence_count", association.evidence_count),
        "contradictory_evidence_count": getattr(association, "contradictory_evidence_count", 0),
        "confidence_score": association.confidence_score,
        "decision_explanation": association.decision_explanation,
        "distinct_days": association.distinct_days,
        "first_seen_at": association.first_seen_at,
        "last_seen_at": association.last_seen_at,
        "archived_at": association.archived_at,
        "review_events": [
            {
                "id": str(event.id),
                "action": event.action,
                "old_status": event.old_status,
                "new_status": event.new_status,
                "note": event.note,
                "reviewer_user_id": str(event.reviewer_user_id) if event.reviewer_user_id else None,
                "created_at": event.created_at,
            }
            for event in review_events
        ],
        "evidence": evidence,
    }
