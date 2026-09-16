"""Flat lookups: vehicles, rules, incidents, the daily digest.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from services.agent.tools import _common
from services.agent.tools._common import (
    _MAX_WINDOW_HOURS,
    _clamp_hours,
    _clamp_limit,
    _to_uuid_set,
)
from shared.models import (
    Camera,
    DailyDigest,
    Incident,
    Rule,
    Vehicle,
)

_GET_VEHICLES_SCHEMA = {
    "type": "object",
    "properties": {
        "plate": {
            "type": "string",
            "description": "Filter to vehicles whose license plate contains this text (case-insensitive).",
        },
        "query": {
            "type": "string",
            "description": (
                "Filter to vehicles whose description/make/model/color/type contains this,"
                " e.g. 'red', 'nissan', 'truck', 'forklift'."
            ),
        },
        "hours": {
            "type": "integer",
            "description": "Only vehicles seen within the last N hours. Default 168 (7 days). Use 720 for 30 days.",
        },
        "limit": {"type": "integer", "description": "Max vehicles to return. Default 20."},
    },
    "additionalProperties": False,
}


async def get_vehicles(
    ctx: dict,
    *,
    plate: str | None = None,
    query: str | None = None,
    hours: int = 168,
    limit: int = 20,
) -> dict:
    """Vehicles identified by license plate, with description + first/last
    seen. Best tool for 'when did the red Nissan arrive', 'what was the
    plate of the truck', 'which vehicles came by today'. Each vehicle is one
    plate-keyed identity. cheap, one indexed pass over the vehicles table."""
    db = ctx["db"]
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
    stmt = select(Vehicle).where(Vehicle.last_seen_at >= since).order_by(Vehicle.last_seen_at.desc())
    rows = (await db.execute(stmt)).scalars().all()

    pl = (plate or "").strip().upper()
    q = (query or "").strip().lower()
    out: list[dict] = []
    for v in rows:
        if pl and pl not in (v.license_plate or "").upper():
            continue
        if q:
            hay = " ".join(
                str(x or "") for x in (v.description, v.make, v.model, v.color, v.vehicle_type, v.display_name)
            ).lower()
            if q not in hay:
                continue
        out.append({
            "id": str(v.id),
            "name": v.display_name,
            "license_plate": v.license_plate,
            "type": v.vehicle_type,
            "color": v.color,
            "make": v.make,
            "model": v.model,
            "description": v.description,
            "first_seen_at": v.first_seen_at.isoformat() if v.first_seen_at else None,
            "last_seen_at": v.last_seen_at.isoformat() if v.last_seen_at else None,
            "sighting_count": v.sighting_count,
        })
        if len(out) >= max(1, limit):
            break
    return {"vehicles": out, "count": len(out)}


_LIST_RULES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name_contains": {
            "type": "string", "minLength": 1, "maxLength": 255,
            "description": "Case-insensitive substring match on rule name.",
        },
        "enabled_only": {"type": "boolean", "default": False},
    },
}


async def list_rules(
    ctx: dict,
    name_contains: str | None = None,
    enabled_only: bool = False,
) -> dict:
    """List automation rules so rule names/ids can be discovered before
    querying their firings with get_events."""
    db = ctx["db"]
    query = select(Rule).order_by(Rule.created_at)
    if enabled_only:
        query = query.where(Rule.enabled == True)  # noqa: E712
    if name_contains:
        query = query.where(func.lower(Rule.name).like(f"%{name_contains.strip().lower()}%"))
    rows = (await db.execute(query)).scalars().all()
    from services.agent.tools.household import _household_mode
    from shared.household_mode import rule_active_in

    mode = await _household_mode()
    return {
        "count": len(rows),
        "household_mode": mode,
        "rules": [
            {
                "rule_id": str(r.id),
                "name": r.name,
                "enabled": r.enabled,
                "trigger": (r.trigger_pattern or {}).get("type"),
                "cooldown_seconds": r.cooldown_seconds,
                # Which modes this rule is on in; null means every mode.
                "only_in_modes": (r.conditions or {}).get("modes") or None,
                # True when the rule is enabled but the current mode keeps
                # it quiet. The usual answer to "why no alert".
                "silenced_by_mode": bool(r.enabled) and not rule_active_in(r.conditions, mode),
            }
            for r in rows
        ],
    }


_GET_INCIDENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hours": {
            "type": "integer", "minimum": 1, "maximum": _MAX_WINDOW_HOURS,
            "default": 24,
            "description": "Look-back window over incident start time.",
        },
        "camera_ids": {
            "type": "array", "items": {"type": "string", "format": "uuid"},
            "maxItems": 50,
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
    },
}


async def get_incidents(
    ctx: dict,
    hours: int = 24,
    camera_ids: list[str] | None = None,
    limit: int = 25,
) -> dict:
    """Curated incident clusters (repeat sightings grouped into one
    semantic event, with a closing VLM summary once finalized)."""
    db = ctx["db"]
    user = ctx["user"]
    hours = _clamp_hours(hours)
    limit = _clamp_limit(limit, default=25, max_=100)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    allowed = await _common.accessible_camera_ids(user, db)
    query = (
        select(Incident)
        .where(Incident.started_at >= cutoff)
        .order_by(Incident.started_at.desc())
        .limit(limit)
    )
    if allowed is not None:
        query = query.where(Incident.camera_id.in_(allowed))
    if camera_ids:
        wanted = _to_uuid_set(camera_ids)
        if wanted:
            query = query.where(Incident.camera_id.in_(wanted))
    rows = (await db.execute(query)).scalars().all()
    cam_rows = await db.execute(
        select(Camera.id, Camera.name).where(
            Camera.id.in_({i.camera_id for i in rows} or {uuid.uuid4()})
        )
    )
    cam_names = {cid: cname for cid, cname in cam_rows.all()}
    return {
        "count": len(rows),
        "hours": hours,
        "incidents": [
            {
                "incident_id": str(i.id),
                "camera": cam_names.get(i.camera_id, str(i.camera_id)),
                "kind": i.signature_kind,
                "who_or_what": i.signature_key,
                "started_at": i.started_at.isoformat(),
                "ended_at": i.ended_at.isoformat() if i.ended_at else None,
                "ongoing": not i.finalized,
                "occurrence_count": i.occurrence_count,
                "summary": i.summary_text,
            }
            for i in rows
        ],
    }


_GET_DAILY_DIGEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "limit": {
            "type": "integer", "minimum": 1, "maximum": 7, "default": 1,
            "description": "How many most-recent digests to return.",
        },
    },
}


async def get_daily_digest(ctx: dict, limit: int = 1) -> dict:
    """Pre-computed household daily digests, newest first."""
    db = ctx["db"]
    limit = _clamp_limit(limit, default=1, max_=7)
    rows = (
        await db.execute(
            select(DailyDigest).order_by(DailyDigest.window_end.desc()).limit(limit)
        )
    ).scalars().all()
    return {
        "count": len(rows),
        "digests": [
            {
                "window_start": d.window_start.isoformat(),
                "window_end": d.window_end.isoformat(),
                "summary": d.summary_text,
            }
            for d in rows
        ],
    }


# ── Registry ─────────────────────────────────────────────────────────


