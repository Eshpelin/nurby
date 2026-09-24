"""Read API for connected-incident tracking.

Incidents group consecutive observations on a single camera by
identity signature (named person, face cluster, top object set)
within an idle window. Each row has a stable id so the dashboard
can render a single rolling card across page reloads and across
sessions, and so notifications can dedup against incidents instead
of individual frames.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import ALL, allowed_camera_ids, apply_camera_filter
from shared.database import get_db
from shared.models import (
    Event,
    EventNote,
    Incident,
    IncidentEvent,
    Observation,
    Recording,
    Rule,
    User,
)

router = APIRouter()

_INCIDENT_STATUSES = {"open", "resolved", "dismissed"}


def _serialize(i: Incident) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "camera_id": str(i.camera_id),
        "signature_kind": i.signature_kind,
        "signature_key": i.signature_key,
        "started_at": i.started_at.isoformat(),
        "last_seen_at": i.last_seen_at.isoformat(),
        "ended_at": i.ended_at.isoformat() if i.ended_at else None,
        "finalized": i.finalized,
        "occurrence_count": i.occurrence_count,
        "peak_observation_id": str(i.peak_observation_id) if i.peak_observation_id else None,
        "observation_ids": i.observation_ids,
        "thumbnails": i.thumbnails,
        "summary_text": i.summary_text,
        "summary_provider_name": i.summary_provider_name,
        "conversation_id": str(i.conversation_id) if i.conversation_id else None,
        "created_at": i.created_at.isoformat(),
        # Resolution workflow (#197).
        "status": getattr(i, "status", "open"),
        "resolution_reason": getattr(i, "resolution_reason", None),
        "resolved_at": (r.isoformat() if (r := getattr(i, "resolved_at", None)) else None),
        "resolved_by_user_id": (str(u) if (u := getattr(i, "resolved_by_user_id", None)) else None),
        "assigned_to_user_id": (str(a) if (a := getattr(i, "assigned_to_user_id", None)) else None),
    }


def _serialize_obs(o: Observation) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "camera_id": str(o.camera_id),
        "started_at": o.started_at.isoformat(),
        "ended_at": o.ended_at.isoformat() if o.ended_at else None,
        "vlm_description": o.vlm_description,
        "vlm_provider": o.vlm_provider,
        "thumbnail_path": o.thumbnail_path,
        "object_detections": o.object_detections,
        "person_detections": o.person_detections,
        "primary_vlm_description": o.primary_vlm_description,
        "refined_by_provider_name": o.refined_by_provider_name,
        "refined_at": o.refined_at.isoformat() if o.refined_at else None,
        "incident_id": str(o.incident_id) if o.incident_id else None,
    }


@router.get("")
async def list_incidents(
    camera_id: uuid.UUID | None = Query(default=None),
    finalized: bool | None = Query(default=None),
    signature_kind: str | None = Query(default=None),
    status: str | None = Query(default=None, description="open | resolved | dismissed"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    q = apply_camera_filter(
        select(Incident).order_by(Incident.last_seen_at.desc()),
        allowed,
        Incident.camera_id,
    )
    if camera_id:
        q = q.where(Incident.camera_id == camera_id)
    if status:
        if status not in _INCIDENT_STATUSES:
            raise HTTPException(status_code=422, detail="invalid incident status")
        q = q.where(Incident.status == status)
    if finalized is not None:
        q = q.where(Incident.finalized.is_(finalized))
    if signature_kind:
        q = q.where(Incident.signature_kind == signature_kind)
    if from_:
        q = q.where(Incident.started_at >= from_)
    if to:
        q = q.where(Incident.started_at <= to)
    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    return [_serialize(r) for r in rows]


async def _get_incident_in_scope(
    incident_id: uuid.UUID, current_user: User, db: AsyncSession
) -> Incident:
    row = await db.get(Incident, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL and row.camera_id not in allowed:
        raise HTTPException(status_code=404, detail="incident not found")
    return row


@router.get("/{incident_id}")
async def get_incident(
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_incident_in_scope(incident_id, current_user, db)
    obs_rows: list[Observation] = []
    obs_ids = row.observation_ids or []
    parsed = []
    for x in obs_ids:
        try:
            parsed.append(uuid.UUID(str(x)))
        except (TypeError, ValueError):
            continue
    if parsed:
        obs_rows = list(
            (
                await db.execute(
                    select(Observation)
                    .where(Observation.id.in_(parsed))
                    .order_by(Observation.started_at.asc())
                )
            ).scalars().all()
        )
    payload = _serialize(row)
    payload["observations"] = [_serialize_obs(o) for o in obs_rows]
    # Who handled / owns it, by name + full history, so shared users see it
    # without a second lookup (#197). Permission is already enforced above.
    payload["ownership"] = await _ownership(row, db)
    # Consistent detail (#197): trigger reason + action result of the alerts
    # this incident fired, the related cross-camera sightings, and the exact
    # clip, so an incident is inspected in one place.
    allowed = await allowed_camera_ids(current_user, db)
    payload["alerts"] = await _incident_alerts(db, parsed)
    payload["related_sightings"] = await _related_sightings(db, row, allowed)
    payload["exact_clip"] = await _exact_clip(db, row)
    # Connect the (already permission- and retention-scoped) evidence export
    # into the incident workflow so it is one click, not a separate hunt
    # (#197). The client hits this endpoint with these params; the bundle
    # endpoint re-checks the caller's camera ACL itself (#225/#201).
    payload["evidence_export"] = {
        "path": "/api/recordings/evidence-bundle",
        "params": {
            "camera_id": str(row.camera_id),
            "from": row.started_at.isoformat(),
            "to": row.last_seen_at.isoformat(),
        },
    }
    return payload


def _actor_name(u) -> str | None:
    if u is None:
        return None
    return getattr(u, "display_name", None) or getattr(u, "email", None)


async def _log_event(
    db: AsyncSession,
    incident_id: uuid.UUID,
    action: str,
    actor: User | None,
    *,
    reason: str | None = None,
    detail: str | None = None,
) -> None:
    """Append one workflow transition to the incident's audit log (#197)."""
    db.add(
        IncidentEvent(
            incident_id=incident_id,
            action=action,
            actor_user_id=getattr(actor, "id", None),
            reason=reason,
            detail=detail,
        )
    )


async def _ownership(i: Incident, db: AsyncSession) -> dict[str, Any]:
    """Current handler/assignee plus the full transition history (#197).

    The single ``resolved_by`` pointer is the latest state; ``history`` is the
    append-only audit log so shared users see everyone who handled it and when,
    even across reopens."""
    # Names for the current pointers.
    ptr_ids = [u for u in (i.resolved_by_user_id, i.assigned_to_user_id) if u]
    names: dict[uuid.UUID, str] = {}
    if ptr_ids:
        rows = (
            await db.execute(
                select(User.id, User.display_name, User.email).where(User.id.in_(ptr_ids))
            )
        ).all()
        names = {uid: (dn or email) for uid, dn, email in rows}

    # Transition history, oldest first, with actor names.
    log_rows = (
        await db.execute(
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == i.id)
            .order_by(IncidentEvent.created_at.asc())
        )
    ).scalars().all()
    actor_ids = {e.actor_user_id for e in log_rows if e.actor_user_id}
    actor_names: dict[uuid.UUID, str] = {}
    if actor_ids:
        rows = (
            await db.execute(
                select(User.id, User.display_name, User.email).where(User.id.in_(actor_ids))
            )
        ).all()
        actor_names = {uid: (dn or email) for uid, dn, email in rows}

    history = [
        {
            "action": e.action,
            "actor": actor_names.get(e.actor_user_id) if e.actor_user_id else None,
            "reason": e.reason,
            "detail": e.detail,
            "at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in log_rows
    ]
    return {
        "status": getattr(i, "status", "open"),
        "resolved_by": names.get(i.resolved_by_user_id) if i.resolved_by_user_id else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "resolution_reason": i.resolution_reason,
        "assigned_to": names.get(i.assigned_to_user_id) if i.assigned_to_user_id else None,
        "history": history,
    }


async def _incident_alerts(db: AsyncSession, obs_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """Alerts fired from this incident's observations: the trigger reason (which
    rule) and the action result (delivered / failed / seen), so the detail
    answers 'what fired and did it reach me' without leaving the page (#197)."""
    if not obs_ids:
        return []
    events = (
        await db.execute(
            select(Event).where(Event.observation_id.in_(obs_ids)).order_by(Event.fired_at.asc())
        )
    ).scalars().all()
    if not events:
        return []
    rule_ids = {e.rule_id for e in events if e.rule_id}
    rule_names: dict[uuid.UUID, str] = {}
    if rule_ids:
        rule_names = {
            rid: name
            for rid, name in (
                await db.execute(select(Rule.id, Rule.name).where(Rule.id.in_(rule_ids)))
            ).all()
        }
    # Notes on those alerts, surfaced inline so the workflow shows them too.
    notes_by_event: dict[uuid.UUID, list[dict]] = {}
    ev_ids = [e.id for e in events]
    for n in (
        await db.execute(
            select(EventNote).where(EventNote.event_id.in_(ev_ids)).order_by(EventNote.created_at.asc())
        )
    ).scalars().all():
        notes_by_event.setdefault(n.event_id, []).append(
            {"text": n.text, "source": n.source, "at": n.created_at.isoformat() if n.created_at else None}
        )
    out = []
    for e in events:
        out.append({
            "event_id": str(e.id),
            "fired_at": e.fired_at.isoformat() if e.fired_at else None,
            "severity": e.severity,
            "trigger_reason": rule_names.get(e.rule_id) if e.rule_id else None,
            "action_type": e.action_type,
            "action_status": e.action_status,        # pending | sent | failed
            "action_error": e.action_error,
            "seen": e.acked_at is not None,
            "seen_at": e.acked_at.isoformat() if e.acked_at else None,
            "notes": notes_by_event.get(e.id, []),
        })
    return out


async def _related_sightings(
    db: AsyncSession, incident: Incident, allowed
) -> list[dict[str, Any]]:
    """Sibling incidents on the same cross-camera journey, permission-scoped —
    the 'related sightings' the detail should link to (#197)."""
    if not incident.journey_id:
        return []
    q = apply_camera_filter(
        select(Incident).where(
            Incident.journey_id == incident.journey_id, Incident.id != incident.id
        ),
        allowed,
        Incident.camera_id,
    ).order_by(Incident.started_at.asc())
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": str(r.id),
            "camera_id": str(r.camera_id),
            "started_at": r.started_at.isoformat(),
            "last_seen_at": r.last_seen_at.isoformat(),
            "summary_text": r.summary_text,
            "status": getattr(r, "status", "open"),
        }
        for r in rows
    ]


async def _exact_clip(db: AsyncSession, incident: Incident) -> dict[str, Any] | None:
    """The recording covering the incident's peak moment, so 'open the exact
    clip' is one hop (#197). Falls back to the incident's start when there is
    no peak observation."""
    anchor = None
    if incident.peak_observation_id:
        obs = await db.get(Observation, incident.peak_observation_id)
        anchor = obs.started_at if obs else None
    anchor = anchor or incident.started_at
    if anchor is None:
        return None
    rec = (
        await db.execute(
            select(Recording)
            .where(Recording.camera_id == incident.camera_id)
            .where(Recording.started_at <= anchor)
            .where((Recording.ended_at.is_(None)) | (Recording.ended_at >= anchor))
            .order_by(Recording.started_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if rec is None:
        return None
    return {
        "recording_id": str(rec.id),
        "started_at": rec.started_at.isoformat(),
        "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
        "anchor_at": anchor.isoformat(),
        "thumbnail_path": rec.thumbnail_path,
    }


class ResolveRequest(BaseModel):
    reason: str | None = None


@router.post("/{incident_id}/resolve")
async def resolve_incident(
    incident_id: uuid.UUID,
    body: ResolveRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an incident resolved (handled), recording who and when (#197)."""
    row = await _get_incident_in_scope(incident_id, current_user, db)
    reason = body.reason if body else None
    row.status = "resolved"
    row.resolution_reason = reason
    row.resolved_at = datetime.now(timezone.utc)
    row.resolved_by_user_id = current_user.id
    await _log_event(db, row.id, "resolved", current_user, reason=reason)
    await db.commit()
    await db.refresh(row)
    return {**_serialize(row), "ownership": await _ownership(row, db)}


@router.post("/{incident_id}/dismiss")
async def dismiss_incident(
    incident_id: uuid.UUID,
    body: ResolveRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss an incident (not worth acting on), recording who and when."""
    row = await _get_incident_in_scope(incident_id, current_user, db)
    reason = body.reason if body else None
    row.status = "dismissed"
    row.resolution_reason = reason
    row.resolved_at = datetime.now(timezone.utc)
    row.resolved_by_user_id = current_user.id
    await _log_event(db, row.id, "dismissed", current_user, reason=reason)
    await db.commit()
    await db.refresh(row)
    return {**_serialize(row), "ownership": await _ownership(row, db)}


@router.post("/{incident_id}/reopen")
async def reopen_incident(
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reopen a resolved/dismissed incident, clearing its resolution."""
    row = await _get_incident_in_scope(incident_id, current_user, db)
    row.status = "open"
    row.resolution_reason = None
    row.resolved_at = None
    row.resolved_by_user_id = None
    await _log_event(db, row.id, "reopened", current_user)
    await db.commit()
    await db.refresh(row)
    return {**_serialize(row), "ownership": await _ownership(row, db)}


class AssignRequest(BaseModel):
    user_id: uuid.UUID | None = None  # null clears the assignment


@router.post("/{incident_id}/assign")
async def assign_incident(
    incident_id: uuid.UUID,
    body: AssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign (or unassign) an incident to a user, for business pilots (#197)."""
    row = await _get_incident_in_scope(incident_id, current_user, db)
    assignee = None
    if body.user_id is not None:
        assignee = await db.get(User, body.user_id)
        if assignee is None or not getattr(assignee, "is_active", True):
            raise HTTPException(status_code=404, detail="assignee not found")
    row.assigned_to_user_id = body.user_id
    if body.user_id is None:
        await _log_event(db, row.id, "unassigned", current_user)
    else:
        await _log_event(db, row.id, "assigned", current_user, detail=_actor_name(assignee))
    await db.commit()
    await db.refresh(row)
    return {**_serialize(row), "ownership": await _ownership(row, db)}


class ReinterpretRequest(BaseModel):
    provider_id: uuid.UUID | None = None


@router.post("/{incident_id}/reinterpret")
@router.post("/{incident_id}/resummarize")
async def reinterpret_incident(
    incident_id: uuid.UUID,
    body: ReinterpretRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-interpret an incident with an optional model override."""
    row = await _get_incident_in_scope(incident_id, current_user, db)

    from services.perception.incident_tracker import IncidentFinalizer
    from shared.models import Camera, Provider

    cam = await db.get(Camera, row.camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="camera not found")
    obs_ids = row.observation_ids or []
    parsed = []
    for x in obs_ids:
        try:
            parsed.append(uuid.UUID(str(x)))
        except (TypeError, ValueError):
            continue
    obs_rows: list[Observation] = []
    if parsed:
        obs_rows = list(
            (
                await db.execute(
                    select(Observation)
                    .where(Observation.id.in_(parsed))
                    .order_by(Observation.started_at.asc())
                )
            ).scalars().all()
        )
    if not obs_rows:
        raise HTTPException(status_code=400, detail="no observations to summarize")

    finalizer = IncidentFinalizer()
    provider: Provider | None = None
    if body and body.provider_id:
        provider = await db.get(Provider, body.provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="provider not found")
        db.expunge(provider)
    else:
        provider = await finalizer._resolve_provider(cam)  # noqa: SLF001
    if provider is None:
        # No VLM/LLM provider configured. AI synthesis is optional, so we
        # degrade gracefully instead of 500ing: return the incident as-is
        # (already carries occurrence_count/timestamps/thumbnails) plus a
        # flag the UI uses to surface "add a provider to enable scene
        # descriptions" rather than a hard error. Detection and the rolling
        # incident card keep working without a provider.
        payload = _serialize(row)
        payload["ai_synthesis"] = False
        payload["message"] = "Add an AI provider to enable scene descriptions."
        return payload
    text = await finalizer._build_summary(provider, cam, row, obs_rows)  # noqa: SLF001
    if not text or text.strip().upper().startswith("SKIP"):
        raise HTTPException(status_code=502, detail="summary returned empty")
    await finalizer._patch_summary(  # noqa: SLF001
        inc_id=incident_id,
        summary_text=text.strip(),
        provider_name=provider.name,
    )
    refreshed = await db.get(Incident, incident_id)
    return _serialize(refreshed) if refreshed else _serialize(row)
