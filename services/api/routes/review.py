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

from services.perception.associator import evidence_policy
from shared.app_settings import get_setting
from shared.auth import get_current_user
from shared.camera_access import ALL, allowed_camera_ids, apply_camera_filter
from shared.database import get_db
from shared.models import (
    AssociationEvidence,
    AssociationReviewEvent,
    AudioAuditLog,
    BodyCluster,
    BodyClusterSample,
    Camera,
    EntityAssociation,
    Event,
    FaceCluster,
    FaceClusterSample,
    Incident,
    Notification,
    Observation,
    Person,
    Transcript,
    User,
)
from shared.schemas import ReviewItemResponse, ReviewQueueResponse

router = APIRouter()

_KINDS = {"incident", "alert", "notification", "identity_suggestion", "relationship_suggestion", "camera_health", "privacy_review"}


class RelationshipDecisionBody(BaseModel):
    decision: Literal["confirm", "reject", "defer", "ambiguous", "archive", "revoke", "restore"]
    note: str | None = Field(default=None, max_length=1000)
    # Clients may send the review timestamp they saw.  This prevents an old
    # open tab from overwriting a newer review while preserving retry-safe
    # behavior when the same decision is submitted again.
    expected_reviewed_at: datetime | None = None
    # Only a confirmed audio-name hypothesis may be explicitly linked to an
    # existing person.  This is a review action, never an automatic rename.
    link_person_id: uuid.UUID | None = None
    # A reviewer may instead attach a spoken-name hypothesis to an existing
    # anonymous visual cluster. This preserves the cluster as the identity
    # anchor and still never renames a Person or enrolls a voiceprint.
    link_cluster_id: uuid.UUID | None = None
    link_cluster_kind: Literal["face", "body"] | None = None
    # Co-occurrence hypotheses can be reconciled one side at a time.  These
    # replace only the association endpoint; immutable evidence keeps the
    # anonymous cluster ids that were known at capture time.
    link_subject_person_id: uuid.UUID | None = None
    link_object_person_id: uuid.UUID | None = None
    link_subject_cluster_id: uuid.UUID | None = None
    link_subject_cluster_kind: Literal["face", "body"] | None = None
    link_object_cluster_id: uuid.UUID | None = None
    link_object_cluster_kind: Literal["face", "body"] | None = None


def _association_visible(association: EntityAssociation, allowed) -> bool:
    if allowed is ALL:
        return True
    allowed_ids = {str(camera_id) for camera_id in allowed}
    return bool(allowed_ids.intersection(str(camera_id) for camera_id in (association.camera_histogram or {})))


def _supporting_evidence_count(association: EntityAssociation) -> int:
    """Read support counts from both current and pre-lifecycle rows.

    Before the supporting/contradictory split existed, ``evidence_count`` was
    the only counter. New columns default to zero on those legacy rows, so a
    raw read would make an established association appear unsupported. A
    non-zero contradictory count is authoritative; otherwise legacy support
    falls back to the original total.
    """
    supporting = int(getattr(association, "supporting_evidence_count", 0) or 0)
    contradictory = int(getattr(association, "contradictory_evidence_count", 0) or 0)
    evidence_count = int(getattr(association, "evidence_count", 0) or 0)
    if supporting == 0 and contradictory == 0 and evidence_count > 0:
        return evidence_count
    return supporting


def _scoped_evidence(row: AssociationEvidence, allowed_ids: set[str] | None) -> dict | None:
    """Project one evidence episode without leaking restricted camera sources.

    An episode may contain observations from more than one camera.  We cannot
    safely expose observation ids or a journey URL for a mixed episode unless
    every contributing camera is visible to the caller, so those source
    pointers are redacted while the permitted camera names/ids remain useful.
    """
    cameras = {str(camera_id) for camera_id in (row.camera_ids or [])}
    if allowed_ids is not None:
        # Missing provenance cannot be safely attributed to a camera-scoped
        # caller. Keep it out of the scoped review surface rather than
        # treating an empty set as implicitly visible.
        if not cameras:
            return None
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


def _reconcile_observation_sources(scoped: dict, existing_ids: set[str]) -> dict:
    """Remove stale frame references and report whether any source remains."""
    original = [str(value) for value in (scoped.get("observation_ids") or [])]
    scoped["observation_ids"] = [value for value in original if value in existing_ids]
    scoped["observation_sources_available"] = bool(scoped["observation_ids"])
    return scoped


def _review_visible(camera_id):
    """Match the existing Events review policy for excluded cameras."""
    excluded = select(Camera.id).where(Camera.exclude_from_review.is_(True))
    return or_(camera_id.is_(None), camera_id.not_in(excluded))


def _as_utc(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _summarize_cluster_samples(rows) -> dict[str, dict]:
    """Build a privacy-safe recurrence summary from already scoped samples.

    Distinct days are the escalation signal; raw frame count is deliberately
    not used because one visit can produce many samples. Callers must apply
    camera ACLs before passing rows here.
    """
    grouped: dict[str, list] = {}
    for row in rows:
        key = str(row.cluster_id)
        grouped.setdefault(key, []).append(row)
    summaries: dict[str, dict] = {}
    for key, samples in grouped.items():
        ordered = sorted(samples, key=lambda row: _as_utc(row.captured_at))
        days = sorted({_as_utc(row.captured_at).date().isoformat() for row in ordered})
        summaries[key] = {
            "sample_count": len(ordered),
            "distinct_days": len(days),
            "days": days,
            "camera_ids": sorted({str(row.camera_id) for row in ordered if row.camera_id}),
            "first_seen_at": _as_utc(ordered[0].captured_at) if ordered else None,
            "last_seen_at": _as_utc(ordered[-1].captured_at) if ordered else None,
            "samples": [
                {
                    "id": str(row.id),
                    "captured_at": _as_utc(row.captured_at),
                    "camera_id": str(row.camera_id),
                    "thumbnail_path": row.thumbnail_path,
                }
                for row in ordered[-6:]
            ],
        }
    return summaries


async def _cluster_sample_summaries(db: AsyncSession, sample_model, cluster_ids, allowed):
    if not cluster_ids or allowed is not ALL and not allowed:
        return {}
    query = select(sample_model).where(sample_model.cluster_id.in_(cluster_ids))
    if allowed is not ALL:
        query = query.where(sample_model.camera_id.in_(allowed))
    rows = (await db.execute(query.order_by(sample_model.captured_at.asc()).limit(2000))).scalars().all()
    return _summarize_cluster_samples(rows)


async def _notification_recurrence_evidence(
    db: AsyncSession,
    notification: Notification,
    allowed,
) -> dict | None:
    """Resolve a recurrence notification's linked samples without widening ACLs.

    The dedupe key is private bookkeeping, but it gives the single Review
    Center a stable pointer back to the cluster that caused the notification.
    Invalid or stale markers are intentionally treated as ordinary
    notifications rather than surfaced to the caller.
    """
    marker = getattr(notification, "dedupe_key", None)
    if not isinstance(marker, str) or not marker.startswith("recurring_unknown:"):
        return None
    parts = marker.split(":")
    if len(parts) != 3 or parts[1] not in {"face", "body"}:
        return None
    try:
        cluster_id = uuid.UUID(parts[2])
    except (TypeError, ValueError):
        return None
    sample_model = FaceClusterSample if parts[1] == "face" else BodyClusterSample
    summary = (await _cluster_sample_summaries(db, sample_model, [cluster_id], allowed)).get(str(cluster_id))
    if not summary:
        return {"cluster_kind": parts[1], "cluster_id": str(cluster_id), "sample_count": 0, "distinct_days": 0, "samples": []}
    return {**summary, "cluster_kind": parts[1], "cluster_id": str(cluster_id)}


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
    include_archived: bool = Query(default=False),
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
            recurrence = await _notification_recurrence_evidence(db, notification, allowed)
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
                evidence={
                    "observation_id": notification.observation_id,
                    **({"recurrence": recurrence} if recurrence is not None else {}),
                },
                provenance={"source": "notification", "rule_id": notification.rule_id},
            ))

    if "identity_suggestion" in requested:
        try:
            recurrence_threshold_days = max(1, min(30, int(await get_setting(
                "unknown_recurrence_threshold_days", 3
            ))))
        except (TypeError, ValueError):
            recurrence_threshold_days = 3
        face_query = apply_camera_filter(
            select(FaceCluster)
            .where(FaceCluster.status == "pending")
            .order_by(FaceCluster.last_seen_at.desc()),
            allowed,
            FaceCluster.first_camera_id,
        )
        face_clusters = (await db.execute(face_query.limit(100))).scalars().all()
        face_recurrence = await _cluster_sample_summaries(
            db, FaceClusterSample, [cluster.id for cluster in face_clusters], allowed
        )
        for cluster in face_clusters:
            recurrence = face_recurrence.get(str(cluster.id), {})
            recurrence = {**recurrence, "cluster_kind": "face", "cluster_id": str(cluster.id)}
            visible_count = recurrence.get("sample_count")
            if visible_count is None:
                visible_count = cluster.sighting_count if allowed is ALL else 0
            recurring = int(recurrence.get("distinct_days") or 0) >= recurrence_threshold_days
            items.append(_item(
                source_type="face_cluster",
                source_id=cluster.id,
                kind="identity_suggestion",
                status="open",
                priority="high" if recurring else "normal",
                title="Recurring unknown person needs review" if recurring else "Unknown person needs review",
                summary=(
                    f"Seen across {recurrence.get('distinct_days', 0)} days ({visible_count} samples): "
                    f"{cluster.auto_label_number and f'Unknown {cluster.auto_label_number}' or 'the same unknown person'}"
                ),
                created_at=cluster.first_seen_at,
                updated_at=cluster.last_seen_at,
                camera_id=cluster.first_camera_id,
                unread=True,
                evidence={
                    "sample_thumbnail_path": cluster.sample_thumbnail_path,
                    "sighting_count": visible_count,
                    "first_seen_at": cluster.first_seen_at,
                    "last_seen_at": cluster.last_seen_at,
                    "appearance_description": cluster.appearance_description,
                    "recurrence": recurrence,
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
        body_clusters = (await db.execute(body_query.limit(100))).scalars().all()
        body_recurrence = await _cluster_sample_summaries(
            db, BodyClusterSample, [cluster.id for cluster in body_clusters], allowed
        )
        for cluster in body_clusters:
            recurrence = body_recurrence.get(str(cluster.id), {})
            recurrence = {**recurrence, "cluster_kind": "body", "cluster_id": str(cluster.id)}
            visible_count = recurrence.get("sample_count")
            if visible_count is None:
                visible_count = cluster.sighting_count if allowed is ALL else 0
            recurring = int(recurrence.get("distinct_days") or 0) >= recurrence_threshold_days
            items.append(_item(
                source_type="body_cluster",
                source_id=cluster.id,
                kind="identity_suggestion",
                status="open",
                priority="high" if recurring else "normal",
                title="Recurring unknown appearance needs review" if recurring else "Unknown appearance needs review",
                summary=(
                    f"Seen across {recurrence.get('distinct_days', 0)} days ({visible_count} samples)"
                    " of a recurring body appearance"
                ),
                created_at=cluster.first_seen_at,
                updated_at=cluster.last_seen_at,
                camera_id=cluster.first_camera_id,
                unread=True,
                evidence={
                    "sample_thumbnail_path": cluster.sample_thumbnail_path,
                    "sighting_count": visible_count,
                    "first_seen_at": cluster.first_seen_at,
                    "last_seen_at": cluster.last_seen_at,
                    "appearance_description": cluster.appearance_description,
                    "recurrence": recurrence,
                },
                provenance={"source": "body_cluster", "cluster_status": cluster.status},
            ))

    if "relationship_suggestion" in requested or "identity_suggestion" in requested:
        association_statuses = ["candidate", "ambiguous", "deferred"]
        if include_archived:
            association_statuses.append("archived")
        association_rows = (
            await db.execute(
                select(EntityAssociation)
                .where(
                    or_(
                        EntityAssociation.status.in_(association_statuses),
                        # Repeated evidence may promote a learned edge to
                        # established before a person reviews it. It still
                        # belongs in the queue while the promotion is only
                        # machine-derived; confirmed household assertions
                        # remain profile facts rather than pending work.
                        and_(
                            EntityAssociation.status == "established",
                            EntityAssociation.user_confirmed.is_(False),
                        ),
                    )
                )
                .order_by(EntityAssociation.last_seen_at.desc())
                # Camera visibility is enforced below from the association's
                # evidence histogram. Fetch the bounded review window before
                # applying the ACL so hidden-camera rows cannot consume the
                # visible queue's entire page.
                .limit(1000)
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
                title=("Archived name hypothesis" if association.status == "archived" and association_kind == "identity_suggestion"
                       else "Archived relationship hypothesis" if association.status == "archived"
                       else "Possible name from audio" if association_kind == "identity_suggestion"
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
                unread=association.status != "archived",
                evidence={
                    "visual_candidate": {
                        "kind": association.subject_kind,
                        "id": association.subject_key,
                    } if association_kind == "identity_suggestion" else None,
                    "evidence_count": association.evidence_count,
                    "supporting_evidence_count": _supporting_evidence_count(association),
                    "contradictory_evidence_count": getattr(association, "contradictory_evidence_count", 0),
                    "confidence_score": association.confidence_score,
                    "decision_explanation": association.decision_explanation,
                    "provenance": association.provenance,
                    "distinct_days": association.distinct_days,
                    "first_seen_at": association.first_seen_at,
                    "last_seen_at": association.last_seen_at,
                    "camera_histogram": association.camera_histogram or {},
                    "evidence_policy": evidence_policy(
                        _supporting_evidence_count(association),
                        getattr(association, "contradictory_evidence_count", 0),
                        status=association.status,
                        source=association.source,
                        user_confirmed=association.user_confirmed,
                    ),
                },
                provenance={
                    "source": association.source,
                    "relation": association.relation,
                    "user_confirmed": association.user_confirmed,
                },
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
    relation: str | None = Query(default=None),
    source: str | None = Query(default=None),
    camera_id: uuid.UUID | None = Query(default=None),
    from_at: datetime | None = Query(default=None, description="Only hypotheses last seen at or after this time"),
    to_at: datetime | None = Query(default=None, description="Only hypotheses first seen at or before this time"),
    include_archived: bool = Query(default=False),
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
    # A camera-scoped review surface may list all visible hypotheses. Entity
    # detail views continue to require one endpoint key so an accidental broad
    # request cannot become the default UI query.
    if not any((subject_key, object_key, camera_id)):
        raise HTTPException(status_code=422, detail="subject_key, object_key, or camera_id is required")
    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL and not allowed:
        return []
    query = select(EntityAssociation)
    if not include_archived and status != "archived":
        query = query.where(EntityAssociation.status != "archived")
    query = query.where(EntityAssociation.status != "rejected")
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
    if relation:
        query = query.where(EntityAssociation.relation == relation)
    if source:
        query = query.where(EntityAssociation.source == source)
    if from_at:
        query = query.where(EntityAssociation.last_seen_at >= from_at)
    if to_at:
        query = query.where(EntityAssociation.first_seen_at <= to_at)
    # Apply the ACL in SQL before the bounded candidate window. The Python
    # projection below remains necessary for legacy/null histograms and for
    # mixed-camera evidence redaction, but it must not be the first filter or
    # hidden rows could consume the 1,000-row window and starve visible ones.
    if allowed is not ALL:
        visible_camera_keys = [
            EntityAssociation.camera_histogram.op("?")(str(camera_key))
            for camera_key in allowed
        ]
        query = query.where(or_(*visible_camera_keys))
    if camera_id is not None:
        if allowed is not ALL and camera_id not in allowed:
            return []
        query = query.where(
            EntityAssociation.camera_histogram.op("?")(str(camera_id))
        )
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
            "supporting_evidence_count": _supporting_evidence_count(row),
            "contradictory_evidence_count": getattr(row, "contradictory_evidence_count", 0),
            "confidence_score": row.confidence_score,
            "decision_explanation": row.decision_explanation,
            "provenance": row.provenance,
            "evidence_policy": evidence_policy(
                _supporting_evidence_count(row),
                getattr(row, "contradictory_evidence_count", 0),
                status=row.status,
                source=row.source,
                user_confirmed=row.user_confirmed,
            ),
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

    Archive removes an unconfirmed hypothesis from the active review queue;
    revoke is reversible: it archives a confirmed relationship while keeping
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
            or body.decision == "ambiguous" and association.status == "ambiguous"
            or body.decision == "archive" and association.status in {"candidate", "ambiguous", "deferred", "established"} and not association.user_confirmed
            or body.decision == "revoke" and association.status == "established"
            or body.decision == "restore" and association.status == "archived"
            or body.decision == "revoke" and association.status == "archived" and association.archived_at is not None
            or body.decision == "restore" and association.status == "candidate" and association.archived_at is None
        )
    )
    if not valid_status:
        raise HTTPException(status_code=404, detail="Relationship suggestion not found")

    if body.link_person_id is not None and (
        body.link_cluster_id is not None
        or body.link_subject_person_id is not None
        or body.link_object_person_id is not None
        or body.link_subject_cluster_id is not None
        or body.link_object_cluster_id is not None
    ):
        raise HTTPException(status_code=422, detail="Use one relationship linking form at a time")
    if body.link_cluster_id is not None and (
        body.link_subject_person_id is not None or body.link_object_person_id is not None
        or body.link_subject_cluster_id is not None or body.link_object_cluster_id is not None
    ):
        raise HTTPException(status_code=422, detail="Use one relationship linking form at a time")

    linked_subject = None
    linked_object = None
    if body.link_person_id is not None:
        if body.decision != "confirm" or association.relation != "possibly_named":
            raise HTTPException(
                status_code=422,
                detail="A person link is only valid when confirming a spoken-name hypothesis.",
            )
        linked_person = await db.get(Person, body.link_person_id)
        if linked_person is None:
            raise HTTPException(status_code=404, detail="Person not found")
    linked_cluster = None
    if body.link_cluster_id is not None:
        if body.decision != "confirm" or association.relation != "possibly_named":
            raise HTTPException(
                status_code=422,
                detail="A cluster link is only valid when confirming a spoken-name hypothesis.",
            )
        if body.link_cluster_kind is None:
            raise HTTPException(status_code=422, detail="A visual cluster kind is required")
        if body.link_cluster_kind == "face":
            linked_cluster = await db.get(FaceCluster, body.link_cluster_id)
        else:
            linked_cluster = await db.get(BodyCluster, body.link_cluster_id)
        if linked_cluster is None:
            raise HTTPException(status_code=404, detail="Visual cluster not found")
    if (
        body.link_subject_person_id is not None or body.link_object_person_id is not None
        or body.link_subject_cluster_id is not None or body.link_object_cluster_id is not None
    ):
        if body.decision != "confirm" or association.relation not in {
            "co_present_with", "arrives_with", "accompanies"
        }:
            raise HTTPException(
                status_code=422,
                detail="Subject links are only valid when confirming a co-occurrence hypothesis",
            )
        if association.subject_kind not in {"person", "face_cluster", "body_cluster"} or association.object_kind not in {
            "person", "face_cluster", "body_cluster"
        }:
            raise HTTPException(status_code=422, detail="Only person or anonymous-subject endpoints can be linked")
        if (
            body.link_subject_person_id is not None
            and body.link_object_person_id is not None
            and body.link_subject_person_id == body.link_object_person_id
        ):
            raise HTTPException(status_code=422, detail="A co-occurrence needs two distinct people")
        if body.link_subject_person_id is not None:
            linked_subject = await db.get(Person, body.link_subject_person_id)
            if linked_subject is None:
                raise HTTPException(status_code=404, detail="Subject person not found")
        if body.link_object_person_id is not None:
            linked_object = await db.get(Person, body.link_object_person_id)
            if linked_object is None:
                raise HTTPException(status_code=404, detail="Companion person not found")
        if body.link_subject_cluster_id is not None:
            if body.link_subject_cluster_kind is None:
                raise HTTPException(status_code=422, detail="A subject cluster kind is required")
            linked_subject_cluster = await db.get(
                FaceCluster if body.link_subject_cluster_kind == "face" else BodyCluster,
                body.link_subject_cluster_id,
            )
            if linked_subject_cluster is None:
                raise HTTPException(status_code=404, detail="Subject visual cluster not found")
        else:
            linked_subject_cluster = None
        if body.link_object_cluster_id is not None:
            if body.link_object_cluster_kind is None:
                raise HTTPException(status_code=422, detail="A companion cluster kind is required")
            linked_object_cluster = await db.get(
                FaceCluster if body.link_object_cluster_kind == "face" else BodyCluster,
                body.link_object_cluster_id,
            )
            if linked_object_cluster is None:
                raise HTTPException(status_code=404, detail="Companion visual cluster not found")
        else:
            linked_object_cluster = None
        if (
            body.link_subject_person_id is not None and body.link_subject_cluster_id is not None
            or body.link_object_person_id is not None and body.link_object_cluster_id is not None
        ):
            raise HTTPException(status_code=422, detail="Choose a person or cluster for each endpoint")
        if linked_subject_cluster is not None and linked_object_cluster is not None and linked_subject_cluster.id == linked_object_cluster.id:
            raise HTTPException(status_code=422, detail="A co-occurrence needs two distinct endpoints")

    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL:
        allowed_ids = {str(camera_id) for camera_id in allowed}
        if not any(str(camera_id) in allowed_ids for camera_id in (association.camera_histogram or {})):
            raise HTTPException(status_code=404, detail="Relationship suggestion not found")
        if linked_cluster is not None and linked_cluster.first_camera_id is not None:
            if str(linked_cluster.first_camera_id) not in allowed_ids:
                raise HTTPException(status_code=404, detail="Visual cluster not found")
        for linked_visual_cluster in (locals().get("linked_subject_cluster"), locals().get("linked_object_cluster")):
            if linked_visual_cluster is not None and linked_visual_cluster.first_camera_id is not None:
                if str(linked_visual_cluster.first_camera_id) not in allowed_ids:
                    raise HTTPException(status_code=404, detail="Visual cluster not found")

    already_applied = (
        body.decision == "confirm" and association.status == "established" and association.user_confirmed
        or body.decision == "reject" and association.status == "rejected"
        or body.decision == "defer" and association.status == "deferred"
        or body.decision == "ambiguous" and association.status == "ambiguous"
        or body.decision == "archive" and association.status == "archived"
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
    old_endpoint = {
        "subject_kind": association.subject_kind,
        "subject_key": association.subject_key,
        "object_kind": association.object_kind,
        "object_key": association.object_key,
    }
    association.status = {
        "confirm": "established",
        "reject": "rejected",
        "defer": "deferred",
        "ambiguous": "ambiguous",
        "archive": "archived",
        "revoke": "archived",
        "restore": "candidate",
    }[body.decision]
    association.user_confirmed = body.decision == "confirm"
    if body.decision in {"archive", "revoke"}:
        association.archived_at = datetime.now(timezone.utc)
    elif body.decision == "restore":
        association.archived_at = None
    association.reviewed_at = datetime.now(timezone.utc)
    association.reviewed_by_user_id = current_user.id
    association.review_note = body.note.strip() if body.note else None
    if body.link_person_id is not None:
        association.object_kind = "person"
        association.object_key = str(body.link_person_id)
        association.object_label = linked_person.nickname or linked_person.display_name
        if not association.review_note:
            association.review_note = "Linked spoken-name hypothesis to this person after review."
    elif linked_cluster is not None:
        association.subject_kind = "cluster"
        association.subject_key = str(linked_cluster.id)
        association.review_note = (
            f"Linked spoken-name hypothesis to the existing {body.link_cluster_kind} cluster after review."
        )
    elif linked_subject is not None or linked_object is not None:
        if linked_subject is not None:
            association.subject_kind = "person"
            association.subject_key = str(linked_subject.id)
        if linked_object is not None:
            association.object_kind = "person"
            association.object_key = str(linked_object.id)
            association.object_label = linked_object.nickname or linked_object.display_name
        association.review_note = (
            f"Linked co-occurrence endpoints after review: "
            f"{linked_subject.nickname or linked_subject.display_name if linked_subject else 'anonymous subject'} "
            f"and {linked_object.nickname or linked_object.display_name if linked_object else 'anonymous companion'}."
        )
    if locals().get("linked_subject_cluster") is not None or locals().get("linked_object_cluster") is not None:
        linked_subject_cluster = locals().get("linked_subject_cluster")
        linked_object_cluster = locals().get("linked_object_cluster")
        if linked_subject_cluster is not None:
            association.subject_kind = f"{body.link_subject_cluster_kind}_cluster"
            association.subject_key = str(linked_subject_cluster.id)
        if linked_object_cluster is not None:
            association.object_kind = f"{body.link_object_cluster_kind}_cluster"
            association.object_key = str(linked_object_cluster.id)
            association.object_label = None
        association.review_note = "Linked co-occurrence endpoints to anonymous visual clusters after review."
    db.add(AssociationReviewEvent(
        association_id=association.id,
        reviewer_user_id=current_user.id,
        action=body.decision,
        old_status=old_status,
        new_status=association.status,
        note=association.review_note,
        decision_metadata={
            "link_type": (
                "spoken_name" if body.link_person_id is not None
                else "spoken_name_cluster" if linked_cluster is not None
                else "cooccurrence_endpoints" if linked_subject is not None or linked_object is not None or locals().get("linked_subject_cluster") is not None or locals().get("linked_object_cluster") is not None
                else None
            ),
            "before": old_endpoint,
            "after": {
                "subject_kind": association.subject_kind,
                "subject_key": association.subject_key,
                "object_kind": association.object_kind,
                "object_key": association.object_key,
            },
            "linked_person_id": str(body.link_person_id) if body.link_person_id else None,
            "linked_cluster_id": str(body.link_cluster_id) if body.link_cluster_id else None,
            "linked_cluster_kind": body.link_cluster_kind,
            "linked_subject_person_id": str(body.link_subject_person_id) if body.link_subject_person_id else None,
            "linked_object_person_id": str(body.link_object_person_id) if body.link_object_person_id else None,
            "linked_subject_cluster_id": str(body.link_subject_cluster_id) if body.link_subject_cluster_id else None,
            "linked_subject_cluster_kind": body.link_subject_cluster_kind,
            "linked_object_cluster_id": str(body.link_object_cluster_id) if body.link_object_cluster_id else None,
            "linked_object_cluster_kind": body.link_object_cluster_kind,
        },
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
    # Redact mixed/foreign-camera episodes before collecting source ids. The
    # source lookup below must never query observations that the caller cannot
    # see, even though their ids are stored on the association ledger.
    visible_rows: list[tuple[AssociationEvidence, dict]] = []
    for row in rows:
        scoped = _scoped_evidence(row, allowed_ids)
        if scoped is not None:
            visible_rows.append((row, scoped))

    observation_ids: set[uuid.UUID] = set()
    for _, scoped in visible_rows:
        for value in scoped["observation_ids"]:
            try:
                observation_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError):
                continue
    existing_observation_ids: set[str] = set()
    if observation_ids:
        existing_observation_ids = {
            str(value)
            for value in (
                await db.execute(
                    select(Observation.id).where(Observation.id.in_(observation_ids))
                )
            ).scalars().all()
        }
    evidence = []
    for row, scoped in visible_rows:
        scoped = _reconcile_observation_sources(scoped, existing_observation_ids)
        transcript_id = scoped["transcript_id"]
        transcript = None
        transcript_exists = True
        transcript_edited = False
        if transcript_id:
            try:
                transcript_query = select(Transcript).where(
                    Transcript.id == uuid.UUID(str(transcript_id))
                )
                # Evidence metadata is immutable but may outlive a source
                # correction or an older producer bug. Re-check the
                # transcript's own camera ACL here instead of trusting the
                # association's copied camera_ids as the sole boundary.
                if allowed_ids is not None:
                    transcript_query = transcript_query.where(
                        Transcript.camera_id.in_(
                            [uuid.UUID(camera_id) for camera_id in allowed_ids]
                        )
                    )
                transcript = await db.scalar(transcript_query)
                transcript_exists = transcript is not None
                transcript_edited = bool(transcript and transcript.text_edited)
            except (TypeError, ValueError):
                transcript_exists = False
        if transcript_id and not transcript_exists:
            source_status = "source_expired"
        elif transcript_id and transcript_edited:
            source_status = "source_changed"
        else:
            source_status = (
                "available"
                if scoped["observation_sources_available"] or row.journey_id or transcript_id
                else "source_expired"
            )
        transcript_excerpt = None
        if transcript_exists and transcript is not None and scoped["fully_visible"]:
            transcript_excerpt = {
                "text": (transcript.text or "")[:600],
                "truncated": len(transcript.text or "") > 600,
                "started_at": transcript.started_at,
                "ended_at": transcript.ended_at,
                "provider": transcript.provider,
                "model": transcript.model,
                "confidence": transcript.confidence,
                "speaker_source": transcript.speaker_source,
                "speaker_confidence": transcript.speaker_confidence,
                "mention_span": scoped["metadata"].get("mention_span"),
                "name_span": scoped["metadata"].get("name_span"),
                "word_timing": scoped["metadata"].get("word_timing"),
            }
        evidence.append({
            **scoped,
            "source_status": source_status,
            "transcript_excerpt": transcript_excerpt,
            "source_url": (
                f"/api/transcripts/{transcript_id}" if transcript_id and transcript_exists
                else f"/api/journeys/{row.journey_id}" if row.journey_id and scoped["fully_visible"]
                else None
            ),
        })
    transcript_ids = {
        uuid.UUID(str(item["metadata"]["transcript_id"]))
        for item in evidence
        if item.get("metadata", {}).get("transcript_id")
    }
    transcript_audits: dict[uuid.UUID, list[dict]] = {}
    if transcript_ids:
        audit_rows = (
            await db.execute(
                select(AudioAuditLog)
                .where(AudioAuditLog.transcript_id.in_(transcript_ids))
                .order_by(AudioAuditLog.created_at.desc())
            )
        ).scalars().all()
        for audit in audit_rows:
            transcript_audits.setdefault(audit.transcript_id, []).append({
                "id": str(audit.id),
                "field": audit.field,
                "old_value": audit.old_value,
                "new_value": audit.new_value,
                "created_at": audit.created_at,
            })
    for item in evidence:
        transcript_id = item.get("metadata", {}).get("transcript_id")
        if transcript_id:
            try:
                item["transcript_audits"] = transcript_audits.get(uuid.UUID(str(transcript_id)), [])
            except (TypeError, ValueError):
                item["transcript_audits"] = []

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
        "supporting_evidence_count": _supporting_evidence_count(association),
        "contradictory_evidence_count": getattr(association, "contradictory_evidence_count", 0),
        "confidence_score": association.confidence_score,
        "decision_explanation": association.decision_explanation,
        "provenance": association.provenance,
        "evidence_policy": evidence_policy(
            _supporting_evidence_count(association),
            getattr(association, "contradictory_evidence_count", 0),
            status=association.status,
            source=association.source,
            user_confirmed=association.user_confirmed,
        ),
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
                "decision_metadata": event.decision_metadata or {},
                "reviewer_user_id": str(event.reviewer_user_id) if event.reviewer_user_id else None,
                "created_at": event.created_at,
            }
            for event in review_events
        ],
        "evidence": evidence,
    }
