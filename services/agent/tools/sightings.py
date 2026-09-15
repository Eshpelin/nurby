"""Last-sighting rollups and the raw event feed.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String as SAString
from sqlalchemy import cast, func, or_, select

from services.agent.tools import _common
from services.agent.tools._common import (
    _MAX_WINDOW_HOURS,
    _clamp_hours,
    _clamp_limit,
    _person_journeys,
    _seg_camera_id,
    _thumbnail_url,
    _to_uuid_set,
)
from shared.models import (
    Camera,
    Event,
    Observation,
    Person,
    Rule,
)
from shared.person_alias import display_name_for

_BASELINE_LABELS = ("person", "cat", "dog", "package", "car", "bird")


_GET_LAST_SIGHTINGS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "person_name": {
            "type": "string",
            "description": (
                "Optional. Restrict to a single Person by display_name "
                "(case-insensitive substring). Returns disambiguation "
                "when more than one match."
            ),
            "minLength": 1,
            "maxLength": 255,
        },
        "labels": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 64},
            "maxItems": 12,
            "description": (
                "Optional. Restrict to these YOLO labels (e.g. ['cat']). "
                "Default queries a curated baseline (person, cat, dog, "
                "package, car, bird)."
            ),
        },
        "since_days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 365,
            "default": 30,
            "description": "Search window in days. Defaults to 30.",
        },
    },
}


async def get_last_sightings(
    ctx: dict,
    person_name: str | None = None,
    labels: list[str] | None = None,
    since_days: int = 30,
) -> dict:
    """Return last-seen-at timestamps per named Person and per common
    YOLO label across the full retention window (default 30 days).

    Use this when a question is about where/when an entity was last
    visible and the default 24h `query_observations` window came back
    empty — this is the cheap baseline that avoids blind window
    widening.
    """
    user = ctx["user"]
    db = ctx["db"]

    since_days = max(1, min(365, int(since_days if since_days is not None else 30)))
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    allowed = await _common.accessible_camera_ids(user, db)
    if not allowed:
        return {"persons": [], "labels": [], "since_days": since_days}

    persons_block: list[dict] = []
    disambiguation: list[dict] | None = None

    # ── Person-side lookup ──────────────────────────────────────────
    person_rows: list[Person] = []
    if person_name:
        needle = f"%{person_name.strip().lower()}%"
        # Match the typed name against either the canonical display_name
        # or the household nickname, so "mommy" finds "Salma Bekom".
        rs = await db.execute(
            select(Person).where(
                or_(
                    func.lower(Person.display_name).like(needle),
                    func.lower(Person.nickname).like(needle),
                )
            )
        )
        person_rows = list(rs.scalars().all())
        if len(person_rows) > 1:
            disambiguation = [
                {"person_id": str(p.id), "display_name": display_name_for(p)}
                for p in person_rows
            ]
    else:
        rs = await db.execute(select(Person).order_by(Person.display_name))
        person_rows = list(rs.scalars().all())

    if not disambiguation:
        for p in person_rows:
            # Most recent Journey that touches at least one accessible
            # camera. Journey is the right grain because the pipeline
            # writes a Journey row whenever a Person shows across one
            # or more cameras.
            js = await _person_journeys(
                db, p.display_name, since=cutoff, order_desc=True, limit=1
            )
            j = js[0] if js else None
            if j is None:
                persons_block.append(
                    {
                        "person_id": str(p.id),
                        "display_name": display_name_for(p),
                        "last_seen_at": None,
                        "last_camera_id": None,
                        "last_journey_id": None,
                        "days_since_seen": None,
                    }
                )
                continue
            cams = j.segments or []
            # Filter Journey segments down to cameras the user can see.
            visible = [c for c in cams if _seg_camera_id(c) in allowed] if cams else []
            persons_block.append(
                {
                    "person_id": str(p.id),
                    "display_name": display_name_for(p),
                    "last_seen_at": j.last_seen_at.isoformat() if j.last_seen_at else None,
                    "last_camera_id": str(visible[0]["camera_id"]) if visible else None,
                    "last_camera_name": visible[0].get("camera_name") if visible else None,
                    "last_journey_id": str(j.id),
                    "days_since_seen": (datetime.now(timezone.utc) - j.last_seen_at).days
                    if j.last_seen_at
                    else None,
                }
            )

    # ── Label-side lookup. uses Observation.object_detections JSON ──────────
    target_labels = list(labels) if labels else list(_BASELINE_LABELS)
    label_block: list[dict] = []
    for lab in target_labels:
        # Pull the latest Observation whose detections contains this
        # label. We cannot rely on a single index here so we cast the
        # JSON column to text and use ILIKE as a cheap filter. For a
        # household of typical size + 30d window this is fast enough.
        needle = f'%"label": "{lab}"%'
        row = (
            await db.execute(
                select(Observation)
                .where(Observation.camera_id.in_(allowed))
                .where(Observation.started_at >= cutoff)
                .where(cast(Observation.object_detections, SAString).ilike(needle))
                .order_by(Observation.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            label_block.append(
                {
                    "label": lab,
                    "last_seen_at": None,
                    "last_camera_id": None,
                    "last_observation_id": None,
                    "days_since_seen": None,
                }
            )
            continue
        cam = (
            await db.execute(select(Camera).where(Camera.id == row.camera_id))
        ).scalar_one_or_none()
        label_block.append(
            {
                "label": lab,
                "last_seen_at": row.started_at.isoformat(),
                "last_camera_id": str(row.camera_id),
                "last_camera_name": cam.name if cam else None,
                "last_observation_id": str(row.id),
                "thumbnail_url": _thumbnail_url(row.thumbnail_path),
                "days_since_seen": (datetime.now(timezone.utc) - row.started_at).days,
            }
        )

    out: dict = {
        "since_days": since_days,
        "persons": persons_block,
        "labels": label_block,
    }
    if disambiguation:
        out["disambiguation"] = disambiguation
        out["persons"] = []
    return out


# ── Tool 3c. get_events ───────────────────────────────────────────────


_GET_EVENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hours": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_WINDOW_HOURS,
            "default": 24,
            "description": "Look-back window. Defaults 24h.",
        },
        "rule_ids": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
            "maxItems": 50,
        },
        "rule_name_contains": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": "Case-insensitive substring match on rule name.",
        },
        "action_status": {
            "type": "string",
            "enum": ["pending", "success", "failed", "skipped"],
        },
        "include_payload": {
            "type": "boolean",
            "default": False,
            "description": (
                "Include the per-event payload dict. Off by default to keep responses small;"
                " turn on when you need camera_id or detection labels."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "default": 100,
        },
    },
}


async def get_events(
    ctx: dict,
    hours: int = 24,
    rule_ids: list[str] | None = None,
    rule_name_contains: str | None = None,
    action_status: str | None = None,
    include_payload: bool = False,
    limit: int = 100,
) -> dict:
    """List rule firings (events) over a time window.

    A rule firing is the strongest evidence Nurby has that something
    happened. If a rule "cat eating" fired 7 times today, that's 7
    confirmed feedings; you do NOT need to re-analyze frames to count
    them. Use this BEFORE analyze_clip for any question shaped like
    "how many times did X happen", "when did rule Y fire", or "did
    rule Z fire today".
    """
    db = ctx["db"]
    user = ctx["user"]

    hours = _clamp_hours(hours)
    limit = _clamp_limit(limit, default=100, max_=200)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    allowed = await _common.accessible_camera_ids(user, db)

    # Resolve rule_ids from name substring if needed.
    target_rule_ids: set[uuid.UUID] = set()
    if rule_ids:
        target_rule_ids = _to_uuid_set(rule_ids)
    if rule_name_contains:
        needle = f"%{rule_name_contains.strip().lower()}%"
        named = (
            await db.execute(
                select(Rule.id).where(func.lower(Rule.name).like(needle))
            )
        ).scalars().all()
        target_rule_ids.update(named)
        if not named and not rule_ids:
            # User asked by name and we found no match. Return empty
            # without scanning events.
            return {
                "count": 0,
                "events": [],
                "hours": hours,
                "filter": {"rule_name_contains": rule_name_contains},
            }

    stmt = (
        select(Event, Rule)
        .join(Rule, Rule.id == Event.rule_id, isouter=True)
        .where(Event.fired_at >= cutoff)
    )
    if target_rule_ids:
        stmt = stmt.where(Event.rule_id.in_(target_rule_ids))
    if action_status:
        stmt = stmt.where(Event.action_status == action_status)
    stmt = stmt.order_by(Event.fired_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).all()
    out: list[dict] = []
    for ev, rule in rows:
        # Respect camera ACL. If the event's payload references a
        # camera_id the user can't see, hide it. Events without a
        # camera_id in payload (rare) pass through.
        payload = ev.payload or {}
        cam_id_raw = payload.get("camera_id")
        if cam_id_raw:
            try:
                if uuid.UUID(str(cam_id_raw)) not in allowed:
                    continue
            except (ValueError, TypeError):
                pass
        item = {
            "event_id": str(ev.id),
            "rule_id": str(ev.rule_id) if ev.rule_id else None,
            "rule_name": rule.name if rule else None,
            "fired_at": ev.fired_at.isoformat() if ev.fired_at else None,
            "action_type": ev.action_type,
            "action_status": ev.action_status,
            "acked_at": ev.acked_at.isoformat() if ev.acked_at else None,
            "observation_id": str(ev.observation_id) if ev.observation_id else None,
        }
        if include_payload:
            item["payload"] = payload
        out.append(item)

    return {
        "count": len(out),
        "events": out,
        "hours": hours,
        "filter": {
            "rule_ids": [str(r) for r in target_rule_ids] if target_rule_ids else None,
            "rule_name_contains": rule_name_contains,
            "action_status": action_status,
        },
    }


# ── Tool 3d. summarize_activity ───────────────────────────────────────


