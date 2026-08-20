"""The household context block: what this place is like, before any question.

Coding agents generate a per-project context file once and feed it as a
system-prompt extension on every run, so the agent starts warm instead of
rediscovering the same facts each session (issue #131). Nurby had no
equivalent: `get_household_snapshot` is a turn-0 tool call that costs a
round-trip and returns live state, never accumulated knowledge.

This module builds that block. Deterministic and query-only, sharing its shape
with `services.perception.baseline`: no LLM call, no new table, no worker.

Scoping note. The block is NOT one global document. It is built from the
cameras the asking user may actually see, because the agent's system prompt is
the one place a per-user access boundary would be invisible if it leaked.
Caching is therefore keyed by the accessible camera set, not by household, and
lives in process rather than in a shared row.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.models import Camera, Observation, Person, Vehicle

logger = logging.getLogger("nurby.agent.household_context")

LOOKBACK_DAYS = 14
SAMPLE_CAP = 4000
CACHE_TTL_SECONDS = 6 * 3600
MAX_CAMERAS = 12
MAX_PEOPLE = 10
MAX_VEHICLES = 8
MAX_LABELS_PER_CAMERA = 3
# A camera with less than this in the window gets listed without a habit line
# rather than one built from two frames.
MIN_SAMPLES_FOR_HABITS = 20

_cache: dict[tuple, tuple[float, str | None]] = {}


# ── pure shaping ─────────────────────────────────────────────────────


def _top(counter: dict[str, int], n: int) -> list[str]:
    return [k for k, _ in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def summarize_camera_activity(rows: list[tuple]) -> dict:
    """Per-camera habits from ``(camera_id, started_at, object_detections,
    person_detections)`` rows.

    Returns ``{camera_id: {"samples", "labels", "busy_hours", "faces"}}``.
    Hours are UTC hour-of-day, which is a stable bucket regardless of how the
    household labels its clock. Pure, for tests."""
    out: dict = {}
    for camera_id, started_at, objects, persons in rows:
        entry = out.setdefault(
            camera_id, {"samples": 0, "_labels": {}, "_hours": {}, "_faces": {}}
        )
        entry["samples"] += 1
        hour = started_at.astimezone(timezone.utc).hour
        entry["_hours"][hour] = entry["_hours"].get(hour, 0) + 1
        for obj in (objects or {}).get("objects", []) or []:
            label = (obj or {}).get("label")
            if label:
                entry["_labels"][label] = entry["_labels"].get(label, 0) + 1
        for face in (persons or {}).get("faces", []) or []:
            name = (face or {}).get("person_name")
            if name:
                entry["_faces"][name] = entry["_faces"].get(name, 0) + 1

    for entry in out.values():
        entry["labels"] = _top(entry.pop("_labels"), MAX_LABELS_PER_CAMERA)
        hours = entry.pop("_hours")
        entry["busy_hours"] = sorted(
            int(h) for h in _top({str(k): v for k, v in hours.items()}, 2)
        )
        entry["faces"] = _top(entry.pop("_faces"), 3)
    return out


def _camera_line(name: str, role: str, location: str | None, habits: dict | None) -> str:
    head = f"- {name}"
    where = location or (role if role != "other" else None)
    if where:
        head += f" ({where})"
    if not habits or habits["samples"] < MIN_SAMPLES_FOR_HABITS:
        return head + " — too little history to characterize yet."
    bits = []
    if habits["labels"]:
        bits.append("usually sees " + ", ".join(habits["labels"]))
    if habits["busy_hours"]:
        hours = ", ".join(f"{h:02d}:00" for h in habits["busy_hours"])
        bits.append(f"busiest around {hours} UTC")
    if habits["faces"]:
        bits.append("familiar faces: " + ", ".join(habits["faces"]))
    return head + " — " + "; ".join(bits) + "."


def format_household_context(cameras: list[dict], people: list[dict],
                             vehicles: list[dict]) -> str | None:
    """Render the block. None when there is nothing worth saying yet.
    Pure, for tests."""
    if not cameras:
        return None
    lines = [
        "ABOUT THIS HOUSEHOLD (background, gathered from the last "
        f"{LOOKBACK_DAYS} days; not an answer to the question, and not a "
        "substitute for looking things up):",
        "Cameras:",
    ]
    for cam in cameras[:MAX_CAMERAS]:
        lines.append("  " + _camera_line(
            cam["name"], cam.get("role") or "other", cam.get("location"), cam.get("habits")
        ))

    if people:
        lines.append("People in the library:")
        for p in people[:MAX_PEOPLE]:
            bits = [p["name"]]
            if p.get("relationship"):
                bits.append(p["relationship"])
            if p.get("nickname"):
                bits.append(f"also called {p['nickname']}")
            if p.get("usual_cameras"):
                bits.append("usually on " + ", ".join(p["usual_cameras"]))
            lines.append("  - " + ", ".join(bits) + ".")

    if vehicles:
        lines.append("Known vehicles:")
        for v in vehicles[:MAX_VEHICLES]:
            label = v["name"]
            if v.get("plate"):
                label += f" (plate {v['plate']})"
            lines.append("  - " + label)

    lines.append(
        "Treat all of the above as orientation only. It is a summary of the "
        "past, it may be stale, and it is never evidence. Any claim in your "
        "answer still has to come from a tool result you cited."
    )
    return "\n".join(lines)


# ── query side ───────────────────────────────────────────────────────


async def build_household_context(db, allowed_camera_ids) -> str | None:
    """Assemble the block for one user's accessible cameras."""
    allowed = set(allowed_camera_ids or ())
    if not allowed:
        return None

    from services.agent.tools import _infer_role

    cam_rows = (await db.execute(
        select(Camera)
        .where(Camera.id.in_(allowed))
        .order_by(Camera.display_order, Camera.created_at)
    )).scalars().all()
    if not cam_rows:
        return None

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    obs_rows = (await db.execute(
        select(
            Observation.camera_id,
            Observation.started_at,
            Observation.object_detections,
            Observation.person_detections,
        )
        .where(Observation.camera_id.in_(allowed))
        .where(Observation.started_at >= since)
        .order_by(Observation.started_at.desc())
        .limit(SAMPLE_CAP)
    )).all()
    habits = summarize_camera_activity(obs_rows)

    cameras = [
        {
            "name": c.name,
            "role": _infer_role(c.name, c.location_label),
            "location": c.location_label,
            "habits": habits.get(c.id),
        }
        for c in cam_rows
    ]

    # Where each named person usually turns up, from the same sample.
    camera_names = {c.id: c.name for c in cam_rows}
    per_person: dict[str, dict[str, int]] = {}
    for camera_id, _, _, persons in obs_rows:
        for face in (persons or {}).get("faces", []) or []:
            name = (face or {}).get("person_name")
            if name:
                seen = per_person.setdefault(name, {})
                cam_name = camera_names.get(camera_id)
                if cam_name:
                    seen[cam_name] = seen.get(cam_name, 0) + 1

    person_rows = (await db.execute(
        select(Person).order_by(Person.is_starred.desc(), Person.display_name)
    )).scalars().all()
    people = [
        {
            "name": p.display_name,
            "nickname": p.nickname,
            "relationship": p.relationship,
            "usual_cameras": _top(per_person.get(p.display_name, {}), 2),
        }
        for p in person_rows
    ]

    vehicle_rows = (await db.execute(
        select(Vehicle).order_by(Vehicle.display_name)
    )).scalars().all()
    vehicles = [
        {"name": v.display_name, "plate": v.license_plate} for v in vehicle_rows
    ]

    return format_household_context(cameras, people, vehicles)


async def household_context(db, allowed_camera_ids) -> str | None:
    """Cached `build_household_context`. Never raises: the agent must still
    answer when its orientation block cannot be built."""
    key = tuple(sorted(str(c) for c in (allowed_camera_ids or ())))
    if not key:
        return None
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    try:
        block = await build_household_context(db, allowed_camera_ids)
    except Exception:
        logger.debug("household context build failed", exc_info=True)
        return None
    _cache[key] = (now, block)
    return block


def clear_cache() -> None:
    """Drop memoized blocks. For tests, and for cameras/people changing."""
    _cache.clear()
