"""FindAnything deep-scan: the user-initiated visual search job.

This backs the "Scan the raw footage" button / "Deep visual scan" toggle
(design §3.2). The button click *is* the cost consent, so this is a plain
user-driven job, not an agent-loop escalation (§3.6).

Flow (design §3.3): cheaply pre-filter candidate frames from the index, then
run the grounding model only on those, streaming boxes back as they land.
Person/identity queries are routed away to face-rec (§3.4): grounding cannot
find "Leo", only "a child in a red jacket".

Jobs live in an in-process registry (single API worker) with partial results
the client polls. That keeps V1 free of a new DB table + inbound WS channel;
the trade-off is jobs do not survive an API restart, which is fine for an
interactive, seconds-to-minutes scan.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from services.grounding.cache import get_cached_grounding, store_grounding
from shared.config import settings

logger = logging.getLogger("nurby.search.scan")

# Person-intent cue words: when the query is clearly about *who*, we route to
# the identity stack instead of grounding (which has no concept of identity).
_PERSON_CUE_WORDS = {"who", "person named", "find my", "is home", "came home"}

_REGISTRY_MAX = 50  # bounded; oldest jobs evicted
_JOB_TTL_SECONDS = 1800


@dataclass
class ScanFrameResult:
    observation_id: str
    camera_id: str
    camera_name: str
    started_at: str
    thumbnail_path: str | None
    boxes: list[dict]  # {bbox_norm, is_point, label}


@dataclass
class ScanRouted:
    kind: str  # "person"
    name: str
    message: str


@dataclass
class ScanJob:
    id: str
    user_id: str
    query: str
    status: str = "running"  # running | done | error
    scanned: int = 0
    total: int = 0
    found: int = 0
    results: list[ScanFrameResult] = field(default_factory=list)
    routed: ScanRouted | None = None
    error: str | None = None
    cameras_seen: set[str] = field(default_factory=set)
    leaves_privacy_boundary: bool = False
    created_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        """Honest "what was scanned" line so a 'no' is trustworthy (§3.2)."""
        if self.routed is not None:
            return self.routed.message
        ncams = len(self.cameras_seen)
        cam_word = "camera" if ncams == 1 else "cameras"
        if self.found:
            return f"Found {self.found} match(es) across {self.scanned} frames, {ncams} {cam_word}."
        if self.status == "done":
            return f"Checked {self.scanned} frames across {ncams} {cam_word}. No match for '{self.query}'."
        return f"Scanning… {self.scanned}/{self.total} frames."


class ScanRegistry:
    """In-process job store, bounded + TTL-evicted."""

    def __init__(self) -> None:
        self._jobs: OrderedDict[str, ScanJob] = OrderedDict()

    def create(self, user_id: str, query: str) -> ScanJob:
        self._evict()
        job = ScanJob(id=str(uuid.uuid4()), user_id=user_id, query=query)
        self._jobs[job.id] = job
        return job

    def get(self, scan_id: str) -> ScanJob | None:
        job = self._jobs.get(scan_id)
        if job is None:
            return None
        if time.time() - job.created_at > _JOB_TTL_SECONDS:
            self._jobs.pop(scan_id, None)
            return None
        return job

    def active_for_user(self, user_id: str) -> ScanJob | None:
        for job in reversed(self._jobs.values()):
            if job.user_id == user_id and job.status == "running":
                return job
        return None

    def _evict(self) -> None:
        now = time.time()
        stale = [k for k, j in self._jobs.items() if now - j.created_at > _JOB_TTL_SECONDS]
        for k in stale:
            self._jobs.pop(k, None)
        while len(self._jobs) >= _REGISTRY_MAX:
            self._jobs.popitem(last=False)


_registry = ScanRegistry()


def get_registry() -> ScanRegistry:
    return _registry


async def classify_intent(db, query: str) -> ScanRouted | None:
    """Return a routing decision when the query is about a *known person*.

    Grounding does open-vocabulary text localization, not photo identity, so a
    query naming someone Nurby already knows is answered by the People/journeys
    surface instead (§3.4). Heuristic and deliberately conservative: only an
    explicit known-name (or a strong person cue) routes away.
    """
    q = (query or "").strip().lower()
    if not q:
        return None

    try:
        from sqlalchemy import select

        from shared.models import Person

        rows = await db.execute(select(Person.display_name, Person.nickname))
        names = [n for row in rows.all() for n in row if n]
    except Exception:
        names = []

    for name in names:
        nl = name.strip().lower()
        if not nl:
            continue
        # Whole-word match so "art" doesn't match "Bart".
        if nl in q.split() or f" {nl} " in f" {q} " or q == nl:
            return ScanRouted(
                kind="person",
                name=name,
                message=f"{name} is a known person. Showing their sightings instead of a visual scan.",
            )

    if any(cue in q for cue in _PERSON_CUE_WORDS):
        return ScanRouted(
            kind="person",
            name="",
            message="That looks like a question about a person. Try the People tab or Ask for who-was-here.",
        )
    return None


def _default_frame_loader(thumbnail_path: str | None):
    """Load a stored keyframe as a BGR ndarray, contained to the media root.

    NOTE: today this is the *annotated* thumbnail (YOLO boxes burned in);
    P2 persists a clean keyframe so grounding never localizes a drawn box
    (design §7). Until then results are slightly degraded, not wrong.
    """
    if not thumbnail_path:
        return None
    import cv2

    from shared.paths import resolve_inside

    safe = resolve_inside(thumbnail_path, settings.thumbnails_path)
    if not safe:
        return None
    return cv2.imread(safe)


def _frame_result(cand: dict, boxes: list) -> ScanFrameResult:
    return ScanFrameResult(
        observation_id=str(cand.get("id")),
        camera_id=str(cand.get("camera_id")),
        camera_name=cand.get("camera_name") or "",
        started_at=cand.get("started_at") or "",
        thumbnail_path=cand.get("thumbnail_path"),
        boxes=boxes,
    )


async def run_scan(
    job: ScanJob,
    *,
    camera_id: uuid.UUID | None,
    time_from: datetime | None,
    time_to: datetime | None,
    max_frames: int,
    client=None,
    frame_loader=None,
) -> None:
    """Execute the scan: pre-filter candidates, ground each, accumulate boxes.

    Never raises. failures land on ``job.error`` / are skipped per frame so a
    single bad frame cannot sink the whole scan.
    """
    from shared.database import async_session

    if client is None:
        from services.grounding.client import get_client

        client = get_client()
    if frame_loader is None:
        frame_loader = _default_frame_loader

    max_frames = max(1, min(max_frames, settings.grounding_max_frames))

    try:
        async with async_session() as db:
            routed = await classify_intent(db, job.query)
            if routed is not None:
                job.routed = routed
                job.status = "done"
                return

            from services.search.query import search_observations

            candidates = await search_observations(
                db,
                query=job.query,
                camera_id=camera_id,
                time_from=time_from,
                time_to=time_to,
                limit=max_frames,
            )

        job.total = len(candidates)
        if not candidates:
            job.status = "done"
            return

        revision = settings.grounding_model_revision
        for cand in candidates:
            job.scanned += 1
            obs_id = cand.get("id")
            job.cameras_seen.add(str(cand.get("camera_id")))

            # Persistent cache: a prior scan of this frame+prompt is reused, so
            # the GPU never re-runs and once-located terms come back instantly
            # (design §7). A miss / no-DB degrades silently to a fresh ground.
            cached = await get_cached_grounding(obs_id, job.query, revision)
            if cached is not None:
                if cached.get("found"):
                    job.found += 1
                    job.results.append(_frame_result(cand, cached.get("boxes") or []))
                continue

            frame = None
            try:
                frame = await asyncio.to_thread(frame_loader, cand.get("thumbnail_path"))
            except Exception:
                logger.debug("scan frame load failed for obs %s", obs_id, exc_info=True)
            if frame is None:
                continue

            result = await client.ground(frame, job.query, interactive=True)
            if result.leaves_privacy_boundary:
                job.leaves_privacy_boundary = True
            if result.error:
                logger.debug("grounding error during scan: %s", result.error)
                continue

            boxes_payload = [
                {"bbox_norm": list(b.bbox_norm), "is_point": b.is_point, "label": b.label}
                for b in result.boxes
            ]
            # Teach the index: persist the hit (and the miss) for next time.
            await store_grounding(
                obs_id, job.query, revision,
                found=result.found, corroborated=False, boxes=boxes_payload,
            )
            if result.found:
                job.found += 1
                job.results.append(_frame_result(cand, boxes_payload))
        job.status = "done"
    except Exception as exc:
        logger.exception("scan job %s failed", job.id)
        job.status = "error"
        job.error = str(exc)
