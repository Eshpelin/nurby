"""Read API for cross-camera journey tracking.

A journey groups incidents for the same subject across multiple
cameras within an idle window. Each row carries a time-ordered
segment list and a list of camera-to-camera transitions so the UI
can render a path without joining back to incidents.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import ALL, AllowedCameras, allowed_camera_ids
from shared.database import get_db
from shared.models import Incident, Journey, User

router = APIRouter()


def _restrict_to_visible(query, allowed: AllowedCameras):
    """Hide journeys that touch any camera outside ``allowed``.

    A journey aggregates incidents across cameras; its segments,
    transitions and camera counts would leak foreign-camera presence
    if any linked incident sits on a camera the viewer cannot see. So
    we fail closed: a journey is visible only when it has at least one
    incident in scope and none out of scope. ``ALL`` is a no-op.
    """
    if allowed is ALL:
        return query
    in_scope = (
        select(Incident.journey_id)
        .where(Incident.journey_id.is_not(None), Incident.camera_id.in_(allowed))
    )
    foreign = (
        select(Incident.journey_id)
        .where(Incident.journey_id.is_not(None), Incident.camera_id.not_in(allowed))
    )
    return query.where(Journey.id.in_(in_scope), Journey.id.not_in(foreign))


async def _journey_visible(journey_id: uuid.UUID, allowed: AllowedCameras, db: AsyncSession) -> bool:
    """Whether a single journey is fully within ``allowed`` (see above)."""
    if allowed is ALL:
        return True
    cam_rows = (
        await db.execute(
            select(Incident.camera_id).where(Incident.journey_id == journey_id)
        )
    ).all()
    cams = {row[0] for row in cam_rows}
    if not cams:
        # A journey with no linked incidents has no evidence to leak, but
        # also nothing a restricted user is entitled to. Fail closed.
        return False
    return cams.issubset(allowed)


def _serialize(j: Journey) -> dict[str, Any]:
    return {
        "id": str(j.id),
        "subject_kind": j.subject_kind,
        "subject_key": j.subject_key,
        "started_at": j.started_at.isoformat(),
        "last_seen_at": j.last_seen_at.isoformat(),
        "ended_at": j.ended_at.isoformat() if j.ended_at else None,
        "finalized": j.finalized,
        "segments": j.segments or [],
        "transitions": j.transitions or [],
        "cameras_seen_count": j.cameras_seen_count,
        "incidents_count": j.incidents_count,
        "summary_text": j.summary_text,
        "summary_provider_name": j.summary_provider_name,
        "created_at": j.created_at.isoformat(),
    }


@router.get("")
async def list_journeys(
    subject_kind: str | None = Query(default=None),
    subject_key: str | None = Query(default=None),
    finalized: bool | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(_user, db)
    q = _restrict_to_visible(select(Journey), allowed).order_by(Journey.last_seen_at.desc())
    if subject_kind:
        q = q.where(Journey.subject_kind == subject_kind)
    if subject_key:
        q = q.where(Journey.subject_key == subject_key)
    if finalized is not None:
        q = q.where(Journey.finalized.is_(finalized))
    if from_:
        q = q.where(Journey.started_at >= from_)
    if to:
        q = q.where(Journey.started_at <= to)
    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/{journey_id}")
async def get_journey(
    journey_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Journey, journey_id)
    if row is None:
        raise HTTPException(status_code=404, detail="journey not found")
    allowed = await allowed_camera_ids(_user, db)
    if not await _journey_visible(journey_id, allowed, db):
        # 404, not 403, so a foreign journey id is never confirmed.
        raise HTTPException(status_code=404, detail="journey not found")
    payload = _serialize(row)
    # Hydrate linked incidents for the detail view so the UI can show
    # per-camera occurrence counts + thumbnails without a second
    # round-trip.
    incs = (
        await db.execute(
            select(Incident)
            .where(Incident.journey_id == journey_id)
            .order_by(Incident.started_at.asc())
        )
    ).scalars().all()
    payload["incidents"] = [
        {
            "id": str(i.id),
            "camera_id": str(i.camera_id),
            "started_at": i.started_at.isoformat(),
            "last_seen_at": i.last_seen_at.isoformat(),
            "occurrence_count": i.occurrence_count,
            "finalized": i.finalized,
            "summary_text": i.summary_text,
            "thumbnails": i.thumbnails,
            "peak_observation_id": str(i.peak_observation_id) if i.peak_observation_id else None,
        }
        for i in incs
    ]
    return payload


class ReinterpretRequest(BaseModel):
    provider_id: uuid.UUID | None = None


@router.post("/{journey_id}/reinterpret")
@router.post("/{journey_id}/resummarize")
async def reinterpret_journey(
    journey_id: uuid.UUID,
    body: ReinterpretRequest | None = None,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Journey, journey_id)
    if row is None:
        raise HTTPException(status_code=404, detail="journey not found")
    allowed = await allowed_camera_ids(_user, db)
    if not await _journey_visible(journey_id, allowed, db):
        raise HTTPException(status_code=404, detail="journey not found")

    from services.perception.journey_tracker import JourneyFinalizer
    from shared.models import Provider

    finalizer = JourneyFinalizer()
    provider: Provider | None = None
    if body and body.provider_id:
        provider = await db.get(Provider, body.provider_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="provider not found")
        db.expunge(provider)
    else:
        provider = await finalizer._resolve_provider()  # noqa: SLF001
    if provider is None:
        # No VLM/LLM provider configured. AI synthesis is optional, so we
        # degrade gracefully instead of 500ing: return the journey as-is
        # (already carries counts/timestamps/segments) plus a flag the UI
        # uses to show "add a provider to enable narrative summaries"
        # rather than a hard error. Detection, tracking, and the path view
        # keep working without a provider.
        payload = _serialize(row)
        payload["ai_synthesis"] = False
        payload["message"] = "Add an AI provider to enable narrative summaries."
        return payload
    text = await finalizer._build_summary(provider, row)  # noqa: SLF001
    if not text or text.strip().upper().startswith("SKIP"):
        raise HTTPException(status_code=502, detail="summary returned empty")
    await finalizer._patch_summary(  # noqa: SLF001
        jid=journey_id,
        summary_text=text.strip(),
        provider_name=provider.name,
    )
    refreshed = await db.get(Journey, journey_id)
    return _serialize(refreshed) if refreshed else _serialize(row)
