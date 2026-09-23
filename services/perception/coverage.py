"""Monitoring coverage contract (#194).

A user-facing conclusion like "all quiet last night" is only trustworthy if
we can also say *what we were actually able to watch*. This module computes,
per permission-scoped camera and over a window, whether each monitoring
capability (video, recording, detection, AI analysis) was healthy, when a
camera was offline, and, crucially, whether an absence of events was a
genuine quiet period or a coverage gap.

The central distinction (and the AC that matters most): a monitoring gap
must never be summarized as an unqualified quiet period. Each camera gets an
``evidence_state``:

* ``active``      - events were observed in the window.
* ``quiet``       - online, pipeline healthy, simply nothing happened. A real
                    negative you can trust.
* ``outage``      - the camera was offline for some/all of the window; that
                    stretch cannot be called quiet.
* ``unprocessed`` - footage was captured but the analysis pipeline was down
                    (observation-writer or VLM failing), so events may have
                    been missed.

Everything is permission-scoped through ``shared.camera_access`` and never
exposes a camera outside the viewer's allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import component_health, heartbeat
from shared.camera_access import AllowedCameras, apply_camera_filter
from shared.models import Camera, CameraStatusLog, Observation, Recording

# Statuses that mean the stream was up.
_ONLINE = ("live", "recording")


@dataclass
class CameraCoverage:
    camera_id: str
    camera_name: str
    status: str
    evidence_state: str
    last_observation_at: str | None = None
    last_ai_caption_at: str | None = None
    last_recording_at: str | None = None
    outages: list[dict[str, Any]] = field(default_factory=list)
    degradations: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "status": self.status,
            "evidence_state": self.evidence_state,
            "last_observation_at": self.last_observation_at,
            "last_ai_caption_at": self.last_ai_caption_at,
            "last_recording_at": self.last_recording_at,
            "outages": self.outages,
            "degradations": self.degradations,
            "gaps": self.gaps,
        }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _pair_outages(rows: list[CameraStatusLog], window_to: datetime) -> dict[Any, list[dict]]:
    """Turn ordered status transitions into offline intervals per camera.

    An ``offline`` row opens an interval; the next non-offline row for that
    camera closes it. An interval still open at ``window_to`` is reported with
    ``to = None`` (still offline).
    """
    by_cam: dict[Any, list[dict]] = {}
    open_since: dict[Any, datetime] = {}
    for row in rows:
        cam = row.camera_id
        if row.status == "offline":
            open_since.setdefault(cam, row.timestamp)
        elif cam in open_since:
            by_cam.setdefault(cam, []).append(
                {"from": _iso(open_since.pop(cam)), "to": _iso(row.timestamp),
                 "reason": row.reason or "offline"}
            )
    for cam, since in open_since.items():
        by_cam.setdefault(cam, []).append(
            {"from": _iso(since), "to": None, "reason": "still offline"}
        )
    return by_cam


def _pair_degradations(rows: list[CameraStatusLog], window_to: datetime) -> dict[Any, list[dict]]:
    """Pair content-health degraded/recovered edges into visible intervals."""
    by_cam: dict[Any, list[dict]] = {}
    open_since: dict[Any, CameraStatusLog] = {}
    for row in rows:
        cam = row.camera_id
        if row.status == "degraded":
            open_since.setdefault(cam, row)
        elif row.status == "recovered" and cam in open_since:
            start = open_since.pop(cam)
            by_cam.setdefault(cam, []).append(
                {"from": _iso(start.timestamp), "to": _iso(row.timestamp),
                 "reason": start.reason or "degraded"}
            )
    for cam, start in open_since.items():
        by_cam.setdefault(cam, []).append(
            {"from": _iso(start.timestamp), "to": None,
             "reason": start.reason or "still degraded"}
        )
    return by_cam


async def _max_by_camera(db, column, allowed, window_from, window_to, extra=None):
    """``{camera_id: max(column)}`` within the window, permission-scoped."""
    model = column.class_
    q = select(model.camera_id, func.max(column)).where(
        column >= window_from, column <= window_to
    )
    if extra is not None:
        q = q.where(extra)
    q = apply_camera_filter(q, allowed, model.camera_id).group_by(model.camera_id)
    return {cid: ts for cid, ts in (await db.execute(q)).all()}


async def pipeline_health() -> dict[str, Any]:
    """Global pipeline capability, from the same keys the doctor + beacon use."""
    writer = await component_health.get(component_health.OBSERVATION_WRITER)
    vlm = await component_health.get(component_health.VLM)
    return {
        "ingestion": await heartbeat.is_alive(heartbeat.INGESTION),
        "perception": await heartbeat.is_alive(heartbeat.PERCEPTION),
        "observation_writer": (writer or {}).get("status", "unknown"),
        "vlm": (vlm or {}).get("status", "unknown"),
    }


async def compute_coverage(
    db: AsyncSession,
    *,
    allowed: AllowedCameras,
    window_from: datetime,
    window_to: datetime | None = None,
) -> dict[str, Any]:
    """Build the permission-scoped coverage report for the window."""
    window_to = window_to or datetime.now(timezone.utc)

    cam_q = apply_camera_filter(
        select(Camera.id, Camera.name, Camera.status, Camera.recording_mode),
        allowed,
        Camera.id,
    )
    cameras = (await db.execute(cam_q)).all()

    last_obs = await _max_by_camera(db, Observation.started_at, allowed, window_from, window_to)
    last_caption = await _max_by_camera(
        db, Observation.started_at, allowed, window_from, window_to,
        extra=Observation.vlm_description.isnot(None),
    )
    last_rec = await _max_by_camera(db, Recording.started_at, allowed, window_from, window_to)

    status_q = (
        select(CameraStatusLog)
        .where(CameraStatusLog.timestamp >= window_from, CameraStatusLog.timestamp <= window_to)
        .order_by(CameraStatusLog.camera_id, CameraStatusLog.timestamp.asc())
    )
    status_q = apply_camera_filter(status_q, allowed, CameraStatusLog.camera_id)
    status_rows = list((await db.execute(status_q)).scalars().all())
    outages = _pair_outages(status_rows, window_to)
    degradations = _pair_degradations(status_rows, window_to)

    pipeline = await pipeline_health()
    pipeline_broken = (
        pipeline["observation_writer"] == component_health.FAIL
        or pipeline["vlm"] == component_health.FAIL
        or not pipeline["perception"]
    )

    out: list[CameraCoverage] = []
    for cid, name, status, recording_mode in cameras:
        cam_outages = outages.get(cid, [])
        cam_degradations = degradations.get(cid, [])
        obs_at = last_obs.get(cid)
        gaps: list[str] = []

        # Classify the evidence state. Order matters: an outage or a broken
        # pipeline overrides "quiet" so a gap is never mistaken for calm.
        if status not in _ONLINE or cam_outages:
            state = "outage"
            if cam_outages:
                gaps.append(
                    f"Offline for {len(cam_outages)} interval(s) in this window; "
                    "that time cannot be treated as quiet."
                )
            elif status not in _ONLINE:
                gaps.append("Currently offline; live view is not being monitored.")
        elif cam_degradations:
            state = "degraded"
            gaps.append(
                f"Content health degraded for {len(cam_degradations)} interval(s); "
                "that time cannot be treated as quiet."
            )
        elif pipeline_broken:
            state = "unprocessed"
            if pipeline["vlm"] == component_health.FAIL:
                gaps.append("AI analysis is failing; captions may be missing for this period.")
            if pipeline["observation_writer"] == component_health.FAIL:
                gaps.append("The detection pipeline is failing; events may have been missed.")
            if not pipeline["perception"]:
                gaps.append("Perception worker is down; footage is captured but not analyzed.")
        elif obs_at is not None:
            state = "active"
        else:
            state = "quiet"

        # Recording staleness only matters when recording should be happening.
        if recording_mode == "always" and status in _ONLINE and last_rec.get(cid) is None:
            gaps.append("No recording segments landed in this window despite always-on recording.")

        out.append(
            CameraCoverage(
                camera_id=str(cid),
                camera_name=name,
                status=status,
                evidence_state=state,
                last_observation_at=_iso(obs_at),
                last_ai_caption_at=_iso(last_caption.get(cid)),
                last_recording_at=_iso(last_rec.get(cid)),
                outages=cam_outages,
                degradations=cam_degradations,
                gaps=gaps,
            )
        )

    cameras_with_gaps = sum(1 for c in out if c.evidence_state in ("outage", "unprocessed") or c.gaps)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"from": _iso(window_from), "to": _iso(window_to)},
        "pipeline": pipeline,
        "cameras": [c.to_dict() for c in out],
        "summary": {
            "camera_count": len(out),
            "cameras_with_gaps": cameras_with_gaps,
            "any_outage": any(c.evidence_state == "outage" for c in out),
            "fully_covered": cameras_with_gaps == 0 and len(out) > 0,
        },
    }


def coverage_sentences(report: dict[str, Any]) -> list[str]:
    """Flatten a report into short, permission-safe lines for Home banners,
    recaps and Ask answers. Empty when coverage is complete."""
    lines: list[str] = []
    for cam in report.get("cameras", []):
        for gap in cam.get("gaps", []):
            lines.append(f"{cam['camera_name']}: {gap}")
    return lines
