"""Make an Ask answer inspectable: scope, identity certainty, limitations (#198).

Citation verification already tells a user whether a claim is backed by a
source. This adds the other half of trustworthy answers: *what was searched*,
*how sure we are who someone is*, and *what could not be checked*. So a user
can tell an evidence-backed statement from a guess, and a genuine "nothing
found" from a coverage gap that only looks quiet.

The scope/identity helpers are pure (list-of-source-dicts in, dict out) so
they are trivially testable. Coverage limitations touch the DB (camera status
log for outages, oldest observation for the retention floor) and are kept in
their own async helper.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.camera_access import ALL, AllowedCameras, apply_camera_filter
from shared.models import Camera, CameraStatusLog, Observation


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


def summarize_scope(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """The cameras and time span the returned evidence actually covers.

    Derived from the evidence itself (not a promise), so the scope shown can
    never overstate what was searched. ``evidence_from`` / ``evidence_to`` are
    the earliest and latest source timestamps.
    """
    cameras: dict[str, str] = {}
    times: list[datetime] = []
    for s in sources:
        cid = s.get("camera_id")
        if cid:
            cameras[str(cid)] = s.get("camera_name") or "Unknown"
        t = _parse(s.get("started_at"))
        if t:
            times.append(t)
    return {
        "cameras_searched": [{"id": cid, "name": name} for cid, name in sorted(cameras.items(), key=lambda kv: kv[1])],
        "camera_count": len(cameras),
        "evidence_from": min(times).isoformat() if times else None,
        "evidence_to": max(times).isoformat() if times else None,
        "evidence_count": len(sources),
    }


def summarize_identity(
    sources: list[dict[str, Any]], resolve_name: Callable[[dict], str | None]
) -> dict[str, Any]:
    """Split the people in the evidence into three certainty buckets.

    * ``matched`` - a confirmed named person (``resolve_name`` returned a name).
    * ``uncertain`` - a recurring but unnamed identity (a face cluster we can
      track across sightings but have no name for). Count of distinct clusters.
    * ``unidentified`` - a face with no name and no cluster: a one-off unknown.

    Keeping these apart stops an answer from implying "your daughter was here"
    when all we really have is "a recurring unknown face".
    """
    matched: set[str] = set()
    uncertain_clusters: set[str] = set()
    unidentified = 0
    for s in sources:
        for face in (s.get("person_detections") or {}).get("faces", []) or []:
            name = resolve_name(face)
            if name:
                matched.add(name)
                continue
            cid = face.get("cluster_id")
            if cid:
                uncertain_clusters.add(str(cid))
            else:
                unidentified += 1
    return {
        "matched": sorted(matched),
        "uncertain_identities": len(uncertain_clusters),
        "unidentified_faces": unidentified,
    }


async def coverage_limitations(
    db: AsyncSession,
    *,
    allowed: AllowedCameras,
    window_from: datetime,
    window_to: datetime | None = None,
    camera_ids: set | None = None,
) -> list[str]:
    """Human-readable gaps that make an answer honest about what it missed.

    Two sources, both permission-scoped:

    * **Outages** - ``camera_status_logs`` rows flipping a camera to
      ``offline`` inside the window. A recorded gap must never be summarized
      as an unqualified quiet period.
    * **Retention floor** - the oldest observation available. If the window
      reaches before it, older footage was already pruned and cannot be
      searched.
    """
    window_to = window_to or datetime.now(timezone.utc)
    limits: list[str] = []

    # Resolve names for the cameras we might mention.
    cam_q = select(Camera.id, Camera.name)
    if allowed is not ALL:
        cam_q = cam_q.where(Camera.id.in_(allowed) if allowed else Camera.id.is_(None))
    cam_names = {cid: name for cid, name in (await db.execute(cam_q)).all()}

    # Outage transitions in the window.
    status_q = (
        select(CameraStatusLog)
        .where(CameraStatusLog.status == "offline")
        .where(CameraStatusLog.timestamp >= window_from)
        .where(CameraStatusLog.timestamp <= window_to)
        .order_by(CameraStatusLog.timestamp.asc())
    )
    status_q = apply_camera_filter(status_q, allowed, CameraStatusLog.camera_id)
    if camera_ids:
        status_q = status_q.where(CameraStatusLog.camera_id.in_(camera_ids))
    seen_outage: set = set()
    for row in (await db.execute(status_q)).scalars().all():
        if row.camera_id in seen_outage:
            continue
        seen_outage.add(row.camera_id)
        name = cam_names.get(row.camera_id, "A camera")
        when = row.timestamp.astimezone().strftime("%b %d, %-I:%M %p").lower()
        limits.append(f"{name} was offline around {when}; that gap could not be checked.")

    # Retention floor.
    oldest_q = select(func.min(Observation.started_at))
    oldest_q = apply_camera_filter(oldest_q, allowed, Observation.camera_id)
    if camera_ids:
        oldest_q = oldest_q.where(Observation.camera_id.in_(camera_ids))
    oldest = (await db.execute(oldest_q)).scalar_one_or_none()
    if oldest is not None and window_from < oldest:
        floor = oldest.astimezone().strftime("%b %d")
        limits.append(f"Only footage since {floor} is available; anything earlier was not retained.")

    return limits
