"""Scheduled driver for expected-activity absence alerts (#215).

Absence is not a frame event, so it is evaluated off the loop: once a window
has closed (end + grace) this sweep gathers the window's sightings and its
coverage, runs the pure decision in
``services.perception.expected_activity.evaluate_window``, and fires an alert
only when the window was actually covered and nothing expected happened.

Honest about coverage: a degraded/unavailable window reads as ``unknown`` and
never alerts. Household-mode aware: an expectation scoped to home/night is
skipped while the household is away, so an away day is not a nobody-home alarm.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.expected_activity import ExpectedWindow, evaluate_window
from shared.database import async_session
from shared.models import ExpectedActivity, Notification, Observation, Person

logger = logging.getLogger("nurby.perception.expected_activity")

INTERVAL_SECONDS = 300
ANY_PERSON = "__any_person__"
ANY_ACTIVITY = "__any_activity__"


def _parse_hhmm(s: str) -> time:
    hh, mm = (s or "0:0").split(":")
    return time(int(hh), int(mm))


def _subject_key(exp: ExpectedActivity) -> str:
    if exp.subject_kind == "any_person":
        return ANY_PERSON
    if exp.subject_kind == "any_activity":
        return ANY_ACTIVITY
    return exp.subject_key or ""


def _person_match_clause(exp: ExpectedActivity):
    """Prefer person_id; legacy expectations continue matching by name."""
    if getattr(exp, "subject_person_id", None):
        return cast(Observation.person_detections, String).ilike(
            f'%"person_id": "{exp.subject_person_id}"%'
        )
    return cast(Observation.person_detections, String).ilike(
        f'%"person_name": "{exp.subject_key}"%'
    )


def _window_bounds(exp: ExpectedActivity, local_now: datetime) -> tuple[datetime, datetime]:
    """The window's [start, end] as tz-aware local datetimes for the current
    applicable date. Overnight windows (end <= start) end on the next day."""
    start_t, end_t = _parse_hhmm(exp.start_time), _parse_hhmm(exp.end_time)
    start_dt = local_now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
    end_dt = local_now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
    if end_t <= start_t:
        end_dt = end_dt + timedelta(days=1)
    return start_dt, end_dt


def due(exp: ExpectedActivity, local_now: datetime) -> bool:
    """Whether this expectation should be evaluated now (pure, testable).

    True when today is an expected weekday, the window + grace has elapsed, and
    it has not already been evaluated for this window's start date."""
    if not exp.enabled:
        return False
    if local_now.weekday() not in set(exp.weekdays or []):
        return False
    start_dt, end_dt = _window_bounds(exp, local_now)
    deadline = end_dt + timedelta(minutes=int(exp.grace_minutes or 0))
    if local_now < deadline:
        return False
    date_key = start_dt.date().isoformat()
    return exp.last_evaluated_on != date_key


def _mode_ok(exp: ExpectedActivity, mode: str | None) -> bool:
    modes = exp.active_modes
    if not modes:  # None or [] -> active in every mode
        return True
    return mode in modes


async def _gather_sightings(
    db: AsyncSession, exp: ExpectedActivity, start_utc: datetime, end_utc: datetime
) -> tuple[list[dict], dict | None]:
    """Matching sightings within the window + the most recent one overall."""
    key = _subject_key(exp)
    cams = {str(c) for c in (exp.camera_ids or [])}

    q = select(Observation).where(
        Observation.started_at >= start_utc, Observation.started_at <= end_utc
    )
    if exp.subject_kind == "person":
        q = q.where(_person_match_clause(exp))
    elif exp.subject_kind == "any_person":
        q = q.where(Observation.person_detections.isnot(None))
    q = q.order_by(Observation.started_at.asc())
    rows = (await db.execute(q)).scalars().all()

    sightings = [
        {"subject_key": key, "camera_id": str(o.camera_id)}
        for o in rows
        if not cams or str(o.camera_id) in cams
    ]

    # Last sighting overall (evidence), independent of the window.
    lq = select(Observation).order_by(Observation.started_at.desc())
    if exp.subject_kind == "person":
        lq = lq.where(_person_match_clause(exp))
    elif exp.subject_kind == "any_person":
        lq = lq.where(Observation.person_detections.isnot(None))
    last_seen = None
    for o in (await db.execute(lq.limit(20))).scalars().all():
        if cams and str(o.camera_id) not in cams:
            continue
        last_seen = {"camera_id": str(o.camera_id), "at": o.started_at.isoformat()}
        break
    return sightings, last_seen


async def evaluate_one(
    db: AsyncSession, exp: ExpectedActivity, tz, mode: str | None, now_utc: datetime
) -> str | None:
    """Evaluate one expectation; persist the outcome; alert on violation.

    Returns the outcome status, or None when not due."""
    local_now = now_utc.astimezone(tz)
    if not due(exp, local_now):
        return None

    start_dt, end_dt = _window_bounds(exp, local_now)
    date_key = start_dt.date().isoformat()

    if not _mode_ok(exp, mode):
        exp.last_evaluated_on = date_key
        exp.last_status = "skipped_mode"
        await db.commit()
        return "skipped_mode"

    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = end_dt.astimezone(timezone.utc)
    sightings, last_seen = await _gather_sightings(db, exp, start_utc, end_utc)

    # Coverage over the window, scoped to the expectation's cameras (or all).
    from services.perception.coverage import compute_coverage
    from shared.camera_access import ALL

    allowed = {uuid.UUID(str(c)) for c in (exp.camera_ids or [])} or ALL
    coverage_report = await compute_coverage(
        db, allowed=allowed, window_from=start_utc, window_to=end_utc
    )

    window = ExpectedWindow(
        subject_key=_subject_key(exp),
        weekdays=frozenset(exp.weekdays or []),
        start=_parse_hhmm(exp.start_time),
        end=_parse_hhmm(exp.end_time),
        camera_ids=frozenset(str(c) for c in (exp.camera_ids or [])),
    )
    result = evaluate_window(
        window,
        local_now=local_now,
        sightings=sightings,
        last_seen=last_seen,
        coverage=coverage_report.get("cameras", []),
    )

    exp.last_evaluated_on = date_key
    exp.last_status = result["status"]
    if result["status"] == "violated":
        await _fire_absence_alert(db, exp, result, start_dt, end_dt)
    await db.commit()
    return result["status"]


async def _fire_absence_alert(db, exp, result, start_dt, end_dt) -> None:
    """Persist an in-app alert carrying honest absence evidence (#215)."""
    subject = {
        "person": exp.subject_key or "that person",
        "any_person": "anyone",
        "any_activity": "any activity",
    }.get(exp.subject_kind, exp.subject_key or "activity")
    win = f"{exp.start_time}-{exp.end_time}"
    last = result.get("last_seen")
    last_txt = f" Last seen {last['at']}." if last else " No prior sighting on record."
    msg = (
        f"Expected activity missed: {exp.name}. No sign of {subject} during {win}.{last_txt}"
    )
    cam_id = None
    if exp.camera_ids:
        try:
            cam_id = uuid.UUID(str(exp.camera_ids[0]))
        except (TypeError, ValueError):
            cam_id = None
    now = datetime.now(timezone.utc)
    db.add(
        Notification(
            message=msg,
            severity="alert",
            camera_id=cam_id,
            created_at=now,
            delivered_at=now,  # persisted AND delivered in-app
        )
    )
    logger.info("expected-activity violation: %s (%s)", exp.name, win)


class ExpectedActivitySweeper:
    def __init__(self, interval_seconds: int = INTERVAL_SECONDS) -> None:
        self._interval = interval_seconds
        self._running = False

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("expected-activity sweep failed; retrying next cycle")
            await asyncio.sleep(self._interval)

    async def _sweep_once(self) -> None:
        from datetime import timezone as _tz

        from shared.app_settings import get_setting
        from shared.household_mode import DEFAULT_MODE
        from shared.timezone import effective_timezone

        tz = await effective_timezone()
        now_utc = datetime.now(_tz.utc)
        async with async_session() as db:
            mode = await get_setting("household_mode") or DEFAULT_MODE
            exps = (
                await db.execute(select(ExpectedActivity).where(ExpectedActivity.enabled.is_(True)))
            ).scalars().all()
            for exp in exps:
                try:
                    await evaluate_one(db, exp, tz, mode, now_utc)
                except Exception:
                    logger.exception("expected-activity eval failed for %s", exp.id)
