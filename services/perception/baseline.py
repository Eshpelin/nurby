"""Per-camera activity baseline: what this camera normally sees.

The anomaly lens used to judge a single still with no priors, so it could not
know unusual because it had never been shown usual (issue #129). This module
answers "what does this camera normally see at this time of day" from the
observations already in the database, and renders the answer as a short context
block the lens can compare a frame against.

Deliberately deterministic and query-only. no VLM call, no new table, no
migration, no background job. The cost is one bounded SELECT per lookup, cached
in-process for an hour.

Bucketing is coarse on purpose. An exact (weekday, hour) bucket over four weeks
yields four samples on a quiet camera, which is not a baseline. Samples are
drawn from the same hour of day plus or minus one hour, on the same kind of day
(weekday vs weekend), over the lookback window.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared.models import Observation

logger = logging.getLogger("nurby.perception.baseline")

LOOKBACK_DAYS = 28
HOUR_SPREAD = 1  # same hour of day, plus or minus this many hours
SAMPLE_CAP = 500
# Below this, the numbers are noise and the lens is better off with no
# baseline than with a confident-sounding wrong one.
MIN_SAMPLES = 12
CACHE_TTL_SECONDS = 3600
MAX_LABELS_SHOWN = 5
MAX_FACES_SHOWN = 4

_cache: dict[tuple, tuple[float, dict | None]] = {}


# ── pure shaping ─────────────────────────────────────────────────────


def observation_signature(object_detections, person_detections) -> dict:
    """Reduce one observation's raw detection blobs to countable facts.

    Returns ``{"labels": {label: count}, "known_faces": [name],
    "unknown_faces": int}``. Pure, for tests."""
    labels: dict[str, int] = {}
    for obj in (object_detections or {}).get("objects", []) or []:
        label = (obj or {}).get("label")
        if label:
            labels[label] = labels.get(label, 0) + 1

    known: list[str] = []
    unknown = 0
    for face in (person_detections or {}).get("faces", []) or []:
        name = (face or {}).get("person_name")
        if name:
            known.append(name)
        else:
            unknown += 1
    return {"labels": labels, "known_faces": known, "unknown_faces": unknown}


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2)


def summarize_baseline(signatures: list[dict]) -> dict | None:
    """Aggregate observation signatures into "what is normal here".

    Returns None when there are too few samples to say anything honest.
    Pure, for tests."""
    if len(signatures) < MIN_SAMPLES:
        return None

    total = len(signatures)
    counts_by_label: dict[str, list[int]] = {}
    face_freq: dict[str, int] = {}
    frames_with_unknown = 0

    for sig in signatures:
        for label, n in (sig.get("labels") or {}).items():
            counts_by_label.setdefault(label, []).append(n)
        for name in sig.get("known_faces") or []:
            face_freq[name] = face_freq.get(name, 0) + 1
        if sig.get("unknown_faces"):
            frames_with_unknown += 1

    labels = []
    for label, counts in counts_by_label.items():
        labels.append({
            "label": label,
            "presence_rate": len(counts) / total,
            "typical_count": _median(counts),
        })
    # Most-often-present first; ties broken by name so output is stable.
    labels.sort(key=lambda d: (-d["presence_rate"], d["label"]))

    faces = sorted(face_freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "samples": total,
        "labels": labels[:MAX_LABELS_SHOWN],
        "known_faces": [name for name, _ in faces[:MAX_FACES_SHOWN]],
        "unknown_face_rate": frames_with_unknown / total,
    }


def _describe_current(sig: dict) -> str:
    bits = [f"{label} {n}" for label, n in sorted((sig.get("labels") or {}).items())]
    if not bits:
        bits = ["nothing detected"]
    line = "This frame: " + ", ".join(bits) + "."
    known = sig.get("known_faces") or []
    if known:
        line += " Recognized: " + ", ".join(sorted(set(known))) + "."
    if sig.get("unknown_faces"):
        n = sig["unknown_faces"]
        line += f" {n} unrecognized face{'s' if n > 1 else ''}."
    return line


def format_baseline_context(baseline: dict | None, current: dict) -> str | None:
    """Render the comparison block handed to the anomaly lens.

    Returns None when there is no usable baseline, in which case the caller
    should send no context at all rather than an empty one. Pure, for tests."""
    if not baseline:
        return None
    normal_bits = []
    for entry in baseline["labels"]:
        pct = round(entry["presence_rate"] * 100)
        normal_bits.append(
            f"{entry['label']} (typically {entry['typical_count']}, "
            f"present in {pct}% of frames)"
        )
    lines = [
        f"NORMAL FOR THIS CAMERA at this time of day, from "
        f"{baseline['samples']} past frames:",
        "  " + ("; ".join(normal_bits) if normal_bits else "no objects at all"),
    ]
    if baseline["known_faces"]:
        lines.append("  Faces normally seen here: " + ", ".join(baseline["known_faces"]))
    unknown_pct = round(baseline["unknown_face_rate"] * 100)
    lines.append(f"  Unrecognized faces appear in {unknown_pct}% of frames here.")
    lines.append("")
    lines.append(_describe_current(current))
    return "\n".join(lines)


# ── query side ───────────────────────────────────────────────────────


def _bucket_key(camera_id, ts: datetime) -> tuple:
    at = ts.astimezone(timezone.utc)
    return (str(camera_id), at.hour, at.weekday() >= 5)


def _in_bucket(started_at: datetime, hour: int, is_weekend: bool) -> bool:
    """Same kind of day, and within HOUR_SPREAD hours of the target hour.
    Hour distance wraps at midnight. Pure, for tests."""
    at = started_at.astimezone(timezone.utc)
    if (at.weekday() >= 5) != is_weekend:
        return False
    diff = abs(at.hour - hour)
    return min(diff, 24 - diff) <= HOUR_SPREAD


async def camera_baseline(db, camera_id, ts: datetime, exclude_id=None) -> dict | None:
    """What ``camera_id`` normally sees around this time of day.

    Cached in-process for CACHE_TTL_SECONDS per (camera, hour, weekday-kind).
    Returns None when the camera has too little history to compare against."""
    key = _bucket_key(camera_id, ts)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    rows = (await db.execute(
        select(
            Observation.id,
            Observation.started_at,
            Observation.object_detections,
            Observation.person_detections,
        )
        .where(Observation.camera_id == camera_id)
        .where(Observation.started_at >= since)
        .where(Observation.object_detections.is_not(None))
        .order_by(Observation.started_at.desc())
        .limit(SAMPLE_CAP * 8)
    )).all()

    _, hour, is_weekend = key
    signatures = []
    for obs_id, started_at, objects, persons in rows:
        if exclude_id is not None and obs_id == exclude_id:
            continue
        if not _in_bucket(started_at, hour, is_weekend):
            continue
        signatures.append(observation_signature(objects, persons))
        if len(signatures) >= SAMPLE_CAP:
            break

    baseline = summarize_baseline(signatures)
    _cache[key] = (now, baseline)
    return baseline


async def anomaly_context(db, camera_id, ts, object_detections,
                          person_detections, exclude_id=None) -> str | None:
    """The full comparison block for one frame, or None when this camera has
    no usable history yet. Never raises: a baseline failure must not cost the
    caller its lens."""
    try:
        baseline = await camera_baseline(db, camera_id, ts, exclude_id=exclude_id)
        current = observation_signature(object_detections, person_detections)
        return format_baseline_context(baseline, current)
    except Exception:
        logger.debug("baseline lookup failed for camera %s", camera_id, exc_info=True)
        return None


def clear_cache() -> None:
    """Drop memoized baselines. For tests and for config changes."""
    _cache.clear()
