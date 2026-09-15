"""Camera layout and the household snapshot.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from services.agent.tools import _common
from services.agent.tools._common import (
    _alias_map,
    _infer_role,
    _person_journeys,
    _seg_camera_id,
    _subject_names,
)
from shared.models import (
    Camera,
    Journey,
    Observation,
    Person,
)
from shared.person_alias import alias_names, display_name_for

_GET_CAMERA_LAYOUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}


async def get_camera_layout(ctx: dict) -> dict:
    """Bootstrap camera context. Returns every accessible camera plus
    an inferred role and current status. Wave 2 driver should call
    this first when answering location questions."""
    user = ctx["user"]
    db = ctx["db"]

    allowed = await _common.accessible_camera_ids(user, db)
    if not allowed:
        return {"cameras": []}

    rows = (
        await db.execute(
            select(Camera)
            .where(Camera.id.in_(allowed))
            .order_by(Camera.display_order, Camera.created_at)
        )
    ).scalars().all()

    cameras = []
    for c in rows:
        cameras.append(
            {
                "id": str(c.id),
                "name": c.name,
                "location_label": c.location_label,
                "role": _infer_role(c.name, c.location_label),
                "scene_mode": c.scene_mode,
                "status": c.status,
                "timezone": c.timezone,
            }
        )
    return {"cameras": cameras}


# ── Tool 3a. get_household_snapshot ───────────────────────────────────


_GET_HOUSEHOLD_SNAPSHOT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
}


async def get_household_snapshot(ctx: dict) -> dict:
    """Cheap one-call orientation primer. Returns:
       - cameras with last-observation timestamp,
       - named Persons with their last sighting,
       - currently open Journeys (still in progress).

    Designed to be the LLM's FIRST call on most questions so it has
    enough state to ask a sensible follow-up tool call instead of
    blind window-widening.
    """
    user = ctx["user"]
    db = ctx["db"]

    allowed = await _common.accessible_camera_ids(user, db)
    if not allowed:
        return {
            "cameras": [],
            "persons": [],
            "active_journeys": [],
            "now_iso": datetime.now(timezone.utc).isoformat(),
        }

    now = datetime.now(timezone.utc)

    # Cameras + their most-recent observation.
    cam_rows = (
        await db.execute(
            select(Camera)
            .where(Camera.id.in_(allowed))
            .order_by(Camera.display_order, Camera.created_at)
        )
    ).scalars().all()
    cameras: list[dict] = []
    for c in cam_rows:
        last_obs = (
            await db.execute(
                select(Observation.started_at, Observation.id)
                .where(Observation.camera_id == c.id)
                .order_by(Observation.started_at.desc())
                .limit(1)
            )
        ).first()
        last_ts = last_obs[0] if last_obs else None
        cameras.append(
            {
                "id": str(c.id),
                "name": c.name,
                "role": _infer_role(c.name, c.location_label),
                "status": c.status,
                "last_observation_at": last_ts.isoformat() if last_ts else None,
                "last_observation_id": str(last_obs[1]) if last_obs else None,
                "minutes_since_last": int((now - last_ts).total_seconds() // 60)
                if last_ts
                else None,
            }
        )

    # Named Persons + their most-recent Journey.
    person_rows = (await db.execute(select(Person).order_by(Person.display_name))).scalars().all()
    persons: list[dict] = []
    for p in person_rows:
        js = await _person_journeys(db, p.display_name, order_desc=True, limit=1)
        j = js[0] if js else None
        persons.append(
            {
                "person_id": str(p.id),
                "display_name": display_name_for(p),
                "relationship": p.relationship,
                "last_seen_at": j.last_seen_at.isoformat() if j and j.last_seen_at else None,
                "last_journey_id": str(j.id) if j else None,
                "hours_since_seen": int((now - j.last_seen_at).total_seconds() // 3600)
                if j and j.last_seen_at
                else None,
            }
        )

    # Currently open Journeys (ended_at IS NULL OR last_seen_at within 5m).
    open_window = now - timedelta(minutes=5)
    active = (
        await db.execute(
            select(Journey)
            .where(Journey.last_seen_at >= open_window)
            .order_by(Journey.last_seen_at.desc())
            .limit(20)
        )
    ).scalars().all()
    amap = await _alias_map(db)
    active_journeys: list[dict] = []
    for j in active:
        # Only surface if it touches an accessible camera.
        segs = j.segments or []
        visible = [s for s in segs if _seg_camera_id(s) in allowed] if segs else []
        if not visible and segs:
            continue
        active_journeys.append(
            {
                "journey_id": str(j.id),
                "person_names": alias_names(_subject_names(j.subject_key), amap)
                if j.subject_kind == "person"
                else [],
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "last_seen_at": j.last_seen_at.isoformat() if j.last_seen_at else None,
                "cameras": [
                    {"id": s.get("camera_id"), "name": s.get("camera_name")}
                    for s in (visible or segs)
                    if isinstance(s, dict)
                ],
            }
        )

    return {
        "now_iso": now.isoformat(),
        "cameras": cameras,
        "persons": persons,
        "active_journeys": active_journeys,
    }


# ── Tool 3b. get_last_sightings ───────────────────────────────────────


# Common labels we surface a baseline for even when not asked. Picks
# the labels users most often ask "where is X?" questions about and
# the existing perception pipeline tags reliably.
