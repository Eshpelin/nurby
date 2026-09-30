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
from shared.camera_access import (
    ALL,
    AllowedCameras,
    allowed_camera_ids,
    apply_camera_filter,
)
from shared.database import get_db
from shared.models import Incident, Journey, User

router = APIRouter()


def _seg_cam_ids(journey: Journey) -> set[uuid.UUID]:
    """Camera UUIDs referenced by a journey's segment list.

    A ``Journey`` has no ``camera_id`` column: the cameras it crossed live in
    the ``segments`` JSON (mirrors ``services/agent/tools/relationships.py``).
    Malformed / missing ids are skipped rather than raising.
    """
    out: set[uuid.UUID] = set()
    for seg in journey.segments or []:
        if not isinstance(seg, dict):
            continue
        cid = seg.get("camera_id")
        if not cid:
            continue
        try:
            out.add(uuid.UUID(str(cid)))
        except (TypeError, ValueError):
            continue
    return out


def _journey_in_scope(journey: Journey, allowed: AllowedCameras) -> bool:
    """True when the caller may see ``journey`` (issue #201).

    Admins / all-mode users (``ALL``) see every journey. A restricted user
    sees a journey only when it touched at least one camera in their
    allowlist. A journey whose segments carry no in-scope camera is hidden.
    """
    if allowed is ALL:
        return True
    return bool(_seg_cam_ids(journey) & allowed)


def _serialize(j: Journey, allowed: AllowedCameras = ALL) -> dict[str, Any]:
    """Serialize a journey without exposing hidden-camera path details.

    A journey is visible when it touches at least one permitted camera, but
    its JSON segments can span cameras the caller cannot see. Restricted
    callers receive only permitted segments/transitions, visible counts and
    timestamps, and no narrative that may mention a hidden camera.
    """
    all_segments = [segment for segment in (j.segments or []) if isinstance(segment, dict)]
    if allowed is ALL:
        segments = all_segments
    else:
        allowed_ids = {str(camera_id) for camera_id in allowed}
        segments = [
            segment for segment in all_segments
            if str(segment.get("camera_id")) in allowed_ids
        ]
    visible_camera_ids = {str(segment.get("camera_id")) for segment in segments if segment.get("camera_id")}
    if allowed is ALL:
        transitions = list(j.transitions or [])
        summary_text = j.summary_text
    else:
        transitions = [
            transition for transition in (j.transitions or [])
            if isinstance(transition, dict)
            and str(transition.get("from_camera_id")) in visible_camera_ids
            and str(transition.get("to_camera_id")) in visible_camera_ids
        ]
        # The existing summary can name cameras from the complete journey.
        summary_text = j.summary_text if len(segments) == len(all_segments) else None

    started_at = j.started_at
    last_seen_at = j.last_seen_at
    ended_at = j.ended_at
    if allowed is not ALL and segments:
        try:
            started_at = datetime.fromisoformat(str(segments[0]["started_at"]))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            last_seen_at = datetime.fromisoformat(str(segments[-1]["last_seen_at"]))
        except (KeyError, TypeError, ValueError):
            pass
        if ended_at is not None and last_seen_at < ended_at:
            ended_at = last_seen_at
    visible_incidents = sum(
        max(1, int(segment.get("occurrence_count") or 1)) for segment in segments
    )
    return {
        "id": str(j.id),
        "subject_kind": j.subject_kind,
        "subject_key": j.subject_key,
        "started_at": started_at.isoformat(),
        "last_seen_at": last_seen_at.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at else None,
        "finalized": j.finalized,
        "segments": segments,
        "transitions": transitions,
        "cameras_seen_count": len(visible_camera_ids) if allowed is not ALL else j.cameras_seen_count,
        "incidents_count": visible_incidents if allowed is not ALL else j.incidents_count,
        "summary_text": summary_text,
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Journey).order_by(Journey.last_seen_at.desc())
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

    # Camera scope (issue #201). Journeys carry their cameras in the
    # segments JSON, so the allowlist cannot be pushed into SQL: fetch the
    # ordered matches, drop journeys that touch no in-scope camera, then
    # paginate in Python. All-mode users keep the cheap SQL offset/limit.
    allowed = await allowed_camera_ids(user, db)
    if allowed is ALL:
        rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
        return [_serialize(r, allowed) for r in rows]
    rows = (await db.execute(q)).scalars().all()
    visible = [r for r in rows if _journey_in_scope(r, allowed)]
    return [_serialize(r) for r in visible[offset : offset + limit]]


@router.get("/{journey_id}")
async def get_journey(
    journey_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Journey, journey_id)
    allowed = await allowed_camera_ids(user, db)
    # 404 (not 403) for a journey outside the caller's cameras, to avoid id
    # probing and match the single-resource convention (issue #201).
    if row is None or not _journey_in_scope(row, allowed):
        raise HTTPException(status_code=404, detail="journey not found")
    payload = _serialize(row, allowed)
    # Hydrate linked incidents for the detail view so the UI can show
    # per-camera occurrence counts + thumbnails without a second
    # round-trip. Restrict to in-scope cameras so a mixed-camera journey
    # cannot leak a foreign camera's incidents.
    incs = (
        await db.execute(
            apply_camera_filter(
                select(Incident).where(Incident.journey_id == journey_id),
                allowed,
                Incident.camera_id,
            ).order_by(Incident.started_at.asc())
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Journey, journey_id)
    allowed = await allowed_camera_ids(user, db)
    # Do not run (or reveal) analysis over a journey the caller cannot see
    # (issue #201): out-of-scope reads as absent.
    if row is None or not _journey_in_scope(row, allowed):
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
