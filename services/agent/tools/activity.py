"""Window summaries of what happened, grouped for a person to read.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from services.agent.tools import _common
from services.agent.tools._common import (
    _MAX_WINDOW_HOURS,
    _clamp_hours,
    _person_journeys,
    _seg_camera_id,
)
from shared.models import (
    Camera,
    Event,
    Observation,
    Person,
    Rule,
)
from shared.person_alias import display_name_for

_SUMMARIZE_ACTIVITY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hours": {
            "type": "integer",
            "minimum": 1,
            "maximum": _MAX_WINDOW_HOURS,
            "default": 24,
            "description": "Look-back window for the rollup. Defaults 24h.",
        },
    },
}


async def summarize_activity(ctx: dict, hours: int = 24) -> dict:
    """Pre-aggregated 'what happened today?' rollup. One call returns.

    - per-Person sightings counts + first/last seen + camera path
      (from Journeys, the cross-camera identity story already curated
      by the perception pipeline);
    - per-rule firing counts (from Events, semantic facts the rule
      engine already confirmed);
    - per-label observation counts and totals (cat, dog, person, etc);
    - camera activity ranking (most active first).

    Designed for narrative questions. 'what happened in the house
    today?', 'give me a 24-hour recap'. The LLM should call this first
    for any such question before issuing per-entity queries; the rollup
    is one DB round-trip and answers most of the question on its own.
    """
    db = ctx["db"]
    user = ctx["user"]

    hours = _clamp_hours(hours)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    now = datetime.now(timezone.utc)
    allowed = await _common.accessible_camera_ids(user, db)

    # ── per-Person Journey rollup ───────────────────────────────────
    persons_block: list[dict] = []
    if allowed:
        rs = await db.execute(select(Person).order_by(Person.display_name))
        for p in rs.scalars().all():
            j_rows = await _person_journeys(
                db, p.display_name, since=cutoff, order_desc=False
            )
            if not j_rows:
                continue
            # Coalesce camera names visible to this user.
            cams_seen: list[str] = []
            seg_count = 0
            for j in j_rows:
                for seg in j.segments or []:
                    cid = _seg_camera_id(seg)
                    if cid is None:
                        continue
                    name = seg.get("camera_name")
                    if cid in allowed and name and name not in cams_seen:
                        cams_seen.append(name)
                    if cid in allowed:
                        seg_count += int(seg.get("occurrence_count") or 0)
            persons_block.append(
                {
                    "person_id": str(p.id),
                    "display_name": display_name_for(p),
                    "sighting_count": len(j_rows),
                    "observation_count": seg_count,
                    "first_seen_at": j_rows[0].started_at.isoformat()
                    if j_rows[0].started_at
                    else None,
                    "last_seen_at": j_rows[-1].last_seen_at.isoformat()
                    if j_rows[-1].last_seen_at
                    else None,
                    "cameras": cams_seen,
                }
            )

    # ── per-rule Event rollup ───────────────────────────────────────
    rules_block: list[dict] = []
    ev_rows = (
        await db.execute(
            select(Event, Rule)
            .join(Rule, Rule.id == Event.rule_id, isouter=True)
            .where(Event.fired_at >= cutoff)
        )
    ).all()
    by_rule: dict[uuid.UUID, dict] = {}
    for ev, rule in ev_rows:
        # Skip events tied to cameras the user can't see.
        payload = ev.payload or {}
        cam_raw = payload.get("camera_id")
        if cam_raw:
            try:
                if uuid.UUID(str(cam_raw)) not in allowed:
                    continue
            except (ValueError, TypeError):
                pass
        rid = ev.rule_id
        if rid is None:
            continue
        bucket = by_rule.setdefault(
            rid,
            {
                "rule_id": str(rid),
                "rule_name": rule.name if rule else None,
                "firing_count": 0,
                "first_fired_at": None,
                "last_fired_at": None,
                "success_count": 0,
                "failed_count": 0,
            },
        )
        bucket["firing_count"] += 1
        ts = ev.fired_at
        if ts:
            ts_iso = ts.isoformat()
            if not bucket["first_fired_at"] or ts_iso < bucket["first_fired_at"]:
                bucket["first_fired_at"] = ts_iso
            if not bucket["last_fired_at"] or ts_iso > bucket["last_fired_at"]:
                bucket["last_fired_at"] = ts_iso
        if ev.action_status == "success":
            bucket["success_count"] += 1
        elif ev.action_status == "failed":
            bucket["failed_count"] += 1
    rules_block = sorted(by_rule.values(), key=lambda r: -r["firing_count"])

    # ── per-label + per-camera observation rollup ──────────────────
    labels_block: dict[str, dict] = {}
    cameras_block: dict[str, dict] = {}
    cam_rows = (
        await db.execute(
            select(Camera).where(Camera.id.in_(allowed)) if allowed else select(Camera).where(False)
        )
    ).scalars().all()
    cam_name_by_id = {c.id: c.name for c in cam_rows}

    obs_rows = (
        await db.execute(
            select(
                Observation.id,
                Observation.camera_id,
                Observation.started_at,
                Observation.object_detections,
                Observation.vlm_description,
                Observation.vlm_late,
            )
            .where(Observation.started_at >= cutoff)
            .where(Observation.camera_id.in_(allowed) if allowed else False)
        )
    ).all() if allowed else []

    # VLM backlog tally. observations missing a vlm_description are
    # still pending on the worker. Observations that were patched late
    # are counted so the answer can honestly say how behind we are.
    vlm_pending = 0
    vlm_late_count = 0

    for obs_id, cam_id, ts, det, vlm_desc, _vlm_late in obs_rows:
        if not vlm_desc:
            vlm_pending += 1
        if _vlm_late:
            vlm_late_count += 1
        cb = cameras_block.setdefault(
            str(cam_id),
            {
                "camera_id": str(cam_id),
                "camera_name": cam_name_by_id.get(cam_id),
                "observation_count": 0,
                "first_observation_at": None,
                "last_observation_at": None,
            },
        )
        cb["observation_count"] += 1
        ts_iso = ts.isoformat() if ts else None
        if ts_iso:
            if not cb["first_observation_at"] or ts_iso < cb["first_observation_at"]:
                cb["first_observation_at"] = ts_iso
            if not cb["last_observation_at"] or ts_iso > cb["last_observation_at"]:
                cb["last_observation_at"] = ts_iso

        # Aggregate labels found in detections JSON. Detection format
        # varies a bit across the pipeline (legacy dict vs list of
        # objects); be defensive about parsing.
        items = det if isinstance(det, list) else (det or {}).get("objects") if isinstance(det, dict) else None
        if isinstance(items, list):
            seen_in_obs: set[str] = set()
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                lab = obj.get("label")
                if not lab or lab in seen_in_obs:
                    continue
                seen_in_obs.add(lab)
                lb = labels_block.setdefault(
                    lab,
                    {"label": lab, "observation_count": 0, "last_seen_at": None},
                )
                lb["observation_count"] += 1
                if ts_iso and (not lb["last_seen_at"] or ts_iso > lb["last_seen_at"]):
                    lb["last_seen_at"] = ts_iso

    return {
        "hours": hours,
        "now_iso": now.isoformat(),
        "persons": persons_block,
        "rules_fired": rules_block,
        "labels": sorted(labels_block.values(), key=lambda x: -x["observation_count"]),
        "cameras": sorted(cameras_block.values(), key=lambda x: -x["observation_count"]),
        "totals": {
            "observations": sum(c["observation_count"] for c in cameras_block.values()),
            "persons_seen": len(persons_block),
            "rules_fired": sum(r["firing_count"] for r in rules_block),
            "unique_labels": len(labels_block),
            "vlm_pending": vlm_pending,
            "vlm_late": vlm_late_count,
        },
    }


# ── Tool 3e. query_relationships ──────────────────────────────────────


# Labels we accept as object-style subjects/objects. Matches the YOLO
# taxonomy the incident tracker writes into Journey.subject_key when
# subject_kind == "object" (see services/perception/incident_tracker.py
# compute_signature) and the labels get_last_sightings baselines on.
