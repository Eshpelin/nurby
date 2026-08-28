"""Learn which identities keep showing up together (issue #148).

A household's useful facts are not single sightings. They are habits:
this person leaves in that car on weekday mornings, these two arrive
together, that operator always takes the same forklift. None of it was
recorded anywhere, so the closest the agent could get to "which car does
Ahmed use" was a substring search for the word "car" inside a JSON blob.

This module folds finalized journeys into :class:`EntityAssociation`
edges. It is deliberately conservative about what becomes a fact:

- **Finalized journeys only.** An open journey is still growing segments,
  and folding it repeatedly would inflate its own evidence.
- **One journey is one piece of evidence**, no matter how many keyframes
  it contains. A van idling beside someone for twenty frames is one event.
- **Promotion gates on distinct days.** Repetition inside a single morning
  is a coincidence; repetition across days is a habit.
- **Household-local time.** "Leaves around 8am" is a statement about the
  household's clock, not UTC.
- **Rejection is permanent.** A rejected edge is skipped entirely, not
  quietly re-accumulated until it crosses the threshold again.
- **Nothing is ever deleted.** Edges that stop matching get archived, and
  archive is recoverable.

Only ``learned`` edges are written here. A ``declared`` edge is an
administrator asserting policy ("this operator is authorized for that
forklift") and must never be produced by inference.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import estop
from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import EntityAssociation, Journey, Observation, Vehicle

logger = logging.getLogger("nurby.perception.associator")


# Days on which a pairing must recur before it is a habit rather than a
# coincidence. Three is low enough to be useful within a week and high
# enough that a single unusual day cannot mint a fact on its own.
DEFAULT_MIN_DISTINCT_DAYS = 3

# Subject kinds worth associating. A body-cluster subject is appearance
# derived and does not survive a change of clothes, so it cannot carry a
# habit across days and is excluded on purpose: the whole value of an
# association is that it spans days.
ASSOCIABLE_SUBJECT_KINDS = {"person", "cluster"}

# Statuses that no longer accept evidence.
TERMINAL_STATUSES = {"rejected"}


# ---- pure helpers --------------------------------------------------------


def local_buckets(when: datetime, tz_name: str) -> tuple[str, int, int]:
    """Return ``(day_key, hour, weekday)`` in household-local time.

    ``day_key`` is ``YYYY-MM-DD``, ``hour`` is 0-23, ``weekday`` is 0-6
    with Monday at 0. An unknown timezone falls back to UTC rather than
    raising: a wrong-by-hours histogram is recoverable, a crashed
    associator silently learns nothing. Pure, for tests.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        local = when.astimezone(ZoneInfo(tz_name or "UTC"))
    except Exception:
        local = when.astimezone(timezone.utc)
    return local.strftime("%Y-%m-%d"), local.hour, local.weekday()


def bump(histogram: dict | None, slot: int, size: int) -> dict:
    """Increment one slot of a fixed-size histogram stored as a dict.

    JSON columns round-trip dict keys as strings, so the slots are keyed
    by string on purpose rather than by int. Pure, for tests.
    """
    out = dict(histogram or {})
    if not 0 <= slot < size:
        return out
    key = str(slot)
    out[key] = int(out.get(key, 0)) + 1
    return out


def next_status(
    current: str, distinct_days: int, min_days: int, user_confirmed: bool
) -> str:
    """The status an edge should hold after folding in new evidence.

    A user's own decision outranks the evidence in both directions: a
    confirmed edge stays established even if the pattern thins out, and a
    rejected edge is never revived. Pure, for tests.
    """
    if current in TERMINAL_STATUSES:
        return current
    if user_confirmed:
        return "established"
    if distinct_days >= min_days:
        return "established"
    # An archived edge that is seeing evidence again becomes a candidate
    # rather than jumping straight back to established.
    return "candidate"


def bump_key(histogram: dict | None, key: str | None) -> dict:
    """Increment a string-keyed counter, e.g. camera id. Pure, for tests."""
    out = dict(histogram or {})
    if not key:
        return out
    out[str(key)] = int(out.get(str(key), 0)) + 1
    return out


def fold(
    assoc: EntityAssociation,
    when: datetime,
    tz_name: str,
    min_days: int,
    camera_id: str | None = None,
) -> bool:
    """Fold one co-presence event into an edge, in place.

    Returns True when the edge was updated, False when it was skipped
    because it is rejected. ``distinct_days`` only advances when the local
    calendar date differs from the last one folded in, so several journeys
    on one morning count once.
    """
    if assoc.status in TERMINAL_STATUSES:
        return False

    day_key, hour, weekday = local_buckets(when, tz_name)

    assoc.evidence_count = int(assoc.evidence_count or 0) + 1
    if assoc.last_day != day_key:
        assoc.distinct_days = int(assoc.distinct_days or 0) + 1
        assoc.last_day = day_key
    assoc.hour_histogram = bump(assoc.hour_histogram, hour, 24)
    assoc.dow_histogram = bump(assoc.dow_histogram, weekday, 7)
    if camera_id:
        assoc.camera_histogram = bump_key(assoc.camera_histogram, camera_id)
    if assoc.first_seen_at is None or when < assoc.first_seen_at:
        assoc.first_seen_at = when
    if assoc.last_seen_at is None or when > assoc.last_seen_at:
        assoc.last_seen_at = when
    assoc.status = next_status(
        assoc.status or "candidate",
        int(assoc.distinct_days or 0),
        min_days,
        bool(assoc.user_confirmed),
    )
    return True


def journey_window(journey: Journey) -> tuple[datetime | None, datetime | None]:
    """The time span a journey covers. Pure, for tests."""
    return journey.started_at, (journey.last_seen_at or journey.ended_at)


def journey_camera_ids(journey: Journey) -> list[uuid.UUID]:
    """Camera ids the journey touched, as uuids. Pure, for tests."""
    out: list[uuid.UUID] = []
    for seg in journey.segments or []:
        cid = seg.get("camera_id") if isinstance(seg, dict) else None
        if not cid:
            continue
        try:
            cid = uuid.UUID(str(cid))
        except (ValueError, AttributeError, TypeError):
            continue
        if cid not in out:
            out.append(cid)
    return out


def vehicles_in(observations) -> dict[str, dict]:
    """``{vehicle_id: {"label", "camera_id"}}`` for identified vehicles.

    Only vehicles that resolved to a Vehicle row count. An unmatched
    detection is a box around something car-shaped, which is not an
    identity and cannot carry an association. The first camera a vehicle
    was seen on within the window is kept, which is where the pairing
    happened. Pure, for tests.
    """
    out: dict[str, dict] = {}
    for obs in observations or []:
        payload = getattr(obs, "vehicle_detections", None) or {}
        for entry in payload.get("vehicles") or []:
            vid = entry.get("vehicle_id")
            if not vid:
                continue
            cam = getattr(obs, "camera_id", None)
            out.setdefault(
                str(vid),
                {
                    "label": entry.get("identity_key"),
                    "camera_id": str(cam) if cam else None,
                },
            )
    return out


# ---- persistence ---------------------------------------------------------


async def record_pairing(
    db: AsyncSession,
    *,
    subject_kind: str,
    subject_key: str,
    object_kind: str,
    object_key: str,
    object_label: str | None,
    relation: str,
    when: datetime,
    tz_name: str,
    min_days: int,
    camera_id: str | None = None,
) -> EntityAssociation | None:
    """Fold one co-presence event into its edge, creating it if needed.

    Returns the edge, or None when a rejected edge declined the evidence.
    Only ever touches ``source="learned"`` rows, so an administrator's
    declared edge is never modified by inference.
    """
    existing = (
        await db.execute(
            select(EntityAssociation)
            .where(EntityAssociation.subject_kind == subject_kind)
            .where(EntityAssociation.subject_key == subject_key)
            .where(EntityAssociation.object_kind == object_kind)
            .where(EntityAssociation.object_key == object_key)
            .where(EntityAssociation.relation == relation)
            .where(EntityAssociation.source == "learned")
            .limit(1)
        )
    ).scalars().first()

    if existing is None:
        existing = EntityAssociation(
            subject_kind=subject_kind,
            subject_key=subject_key,
            object_kind=object_kind,
            object_key=object_key,
            object_label=object_label,
            relation=relation,
            source="learned",
            status="candidate",
            evidence_count=0,
            distinct_days=0,
        )
        db.add(existing)
    elif object_label and existing.object_label != object_label:
        existing.object_label = object_label

    if not fold(existing, when, tz_name, min_days, camera_id=camera_id):
        return None
    return existing


async def process_journey(
    db: AsyncSession, journey: Journey, *, tz_name: str, min_days: int
) -> int:
    """Fold one finalized journey into associations. Returns edges touched."""
    if journey.subject_kind not in ASSOCIABLE_SUBJECT_KINDS:
        return 0
    start, end = journey_window(journey)
    if not (start and end):
        return 0
    cameras = journey_camera_ids(journey)
    if not cameras:
        return 0

    rows = (
        await db.execute(
            select(Observation)
            .where(Observation.camera_id.in_(cameras))
            .where(Observation.started_at >= start)
            .where(Observation.started_at <= end)
            .where(Observation.vehicle_detections.is_not(None))
        )
    ).scalars().all()

    seen_vehicles = vehicles_in(rows)
    await _check_deviations(
        db, journey, seen_vehicles, when=start, tz_name=tz_name
    )

    touched = 0
    for vehicle_id, seen in seen_vehicles.items():
        label = seen.get("label")
        try:
            vehicle = await db.get(Vehicle, uuid.UUID(vehicle_id))
            if vehicle is not None:
                label = vehicle.nickname or vehicle.display_name or label
        except (ValueError, AttributeError, TypeError):
            vehicle = None
        edge = await record_pairing(
            db,
            subject_kind=journey.subject_kind,
            subject_key=journey.subject_key,
            object_kind="vehicle",
            object_key=vehicle_id,
            object_label=label,
            relation="uses",
            when=start,
            tz_name=tz_name,
            min_days=min_days,
            camera_id=seen.get("camera_id"),
        )
        if edge is not None:
            touched += 1
    return touched


async def _check_deviations(
    db: AsyncSession,
    journey: Journey,
    seen_vehicles: dict[str, dict],
    *,
    when: datetime,
    tz_name: str,
) -> None:
    """Compare this journey against what the subject's edges expect.

    Runs BEFORE the journey is folded in, so today's evidence has not yet
    moved the expectation the comparison is made against. Never raises: a
    missed alert must not cost the association it was derived from.

    Detection latency is journey-finalization plus one tick, so an alert
    lands minutes after the fact rather than instantly. That is the right
    trade here: the alert is a statement about a completed visit, and
    firing on a partial one would mean retracting it.
    """
    try:
        from services.perception import deviations

        edges = (
            await db.execute(
                select(EntityAssociation)
                .where(EntityAssociation.subject_kind == journey.subject_kind)
                .where(EntityAssociation.subject_key == journey.subject_key)
                .where(EntityAssociation.relation == "uses")
            )
        ).scalars().all()
        if not edges:
            return
        learned = [e for e in edges if e.source == "learned"]
        cameras = [str(c) for c in journey_camera_ids(journey)]
        present = set(seen_vehicles)

        for edge in learned:
            if not deviations.is_alertable(edge):
                continue

            if str(edge.object_key) in present:
                # The expected pairing happened. Only its timing can be odd.
                seen = seen_vehicles.get(str(edge.object_key)) or {}
                event = deviations.detect_wrong_time(
                    edge,
                    camera_id=seen.get("camera_id") or (cameras[0] if cameras else None),
                    when=when,
                    tz_name=tz_name,
                )
                if event:
                    await deviations.emit(event)
                continue

            # A different object where this one usually is.
            for vehicle_id, seen in seen_vehicles.items():
                event = deviations.detect_unexpected_object(
                    edge,
                    present_object_key=vehicle_id,
                    camera_id=seen.get("camera_id") or "",
                    when=when,
                    tz_name=tz_name,
                )
                if event:
                    await deviations.emit(event)

        # Policy, not habit. Any use of a controlled object by someone with
        # no declared authorization for it, regardless of how established
        # the habit is.
        declared = await _declared_for(db, list(present))
        if declared:
            for vehicle_id, seen in seen_vehicles.items():
                probe = EntityAssociation(
                    subject_kind=journey.subject_kind,
                    subject_key=journey.subject_key,
                    object_kind="vehicle",
                    object_key=vehicle_id,
                    object_label=seen.get("label"),
                    relation="uses",
                    source="learned",
                )
                event = deviations.detect_unauthorized(probe, declared)
                if event:
                    await deviations.emit(event)
    except Exception:
        logger.exception("deviation check failed for journey %s", journey.id)


async def _declared_for(db: AsyncSession, object_keys: list[str]):
    """Every declared authorized_for edge over these objects."""
    if not object_keys:
        return []
    return (
        await db.execute(
            select(EntityAssociation)
            .where(EntityAssociation.relation == "authorized_for")
            .where(EntityAssociation.source == "declared")
            .where(EntityAssociation.object_key.in_(object_keys))
        )
    ).scalars().all()


# ---- worker --------------------------------------------------------------


class Associator:
    """Background pass folding finalized journeys into associations.

    Mirrors JourneyFinalizer's shape. Runs rarely on purpose: an
    association is a statement about days, so there is nothing to gain
    from a tight loop, and the household's CPU is busy decoding video.
    """

    TICK_SECONDS = 300
    BATCH = 25

    def __init__(self) -> None:
        self._stopping = asyncio.Event()
        # (edge_id, local_day) pairs already alerted on, so an absence
        # fires once a day rather than on every tick until midnight.
        self._absence_fired: set[tuple[str, str]] = set()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("associator started")
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except Exception:
                    logger.exception("associator tick failed")
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.TICK_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("associator stopped")


    async def _sweep_absences(self, tz_name: str) -> None:
        """Fire for habits that should have happened by now and have not.

        Absence has no event to hang off, so it needs a sweep. Each edge
        fires at most once per local day: detect_expected_absent checks
        last_day, and _absence_fired keeps the tick from repeating the
        same alert every five minutes until midnight.
        """
        try:
            from services.perception import deviations

            now = datetime.now(timezone.utc)
            today, _, _ = local_buckets(now, tz_name)
            async with async_session() as db:
                edges = (
                    await db.execute(
                        select(EntityAssociation)
                        .where(EntityAssociation.status == "established")
                        .where(EntityAssociation.source == "learned")
                        .limit(500)
                    )
                ).scalars().all()
            for edge in edges:
                marker = (str(edge.id), today)
                if marker in self._absence_fired:
                    continue
                event = deviations.detect_expected_absent(
                    edge, now=now, tz_name=tz_name
                )
                if event:
                    await deviations.emit(event)
                    self._absence_fired.add(marker)
            # Yesterday's markers are dead weight; a day key never repeats.
            self._absence_fired = {
                m for m in self._absence_fired if m[1] == today
            }
        except Exception:
            logger.exception("absence sweep failed")

    async def _tick(self) -> None:
        if not bool(await get_setting("associations_enabled", True)):
            return
        if estop.is_engaged():
            # Household-wide pause. This is background work by
            # definition, so skipping a tick costs nothing: the journeys
            # stay unstamped and are folded in on the next one.
            return
        tz_name = await get_setting("system_timezone") or "UTC"
        min_days = int(
            await get_setting("association_min_distinct_days", DEFAULT_MIN_DISTINCT_DAYS)
        )
        await self._sweep_absences(tz_name)
        async with async_session() as db:
            pending = (
                await db.execute(
                    select(Journey)
                    .where(Journey.finalized.is_(True))
                    .where(Journey.associations_at.is_(None))
                    .order_by(Journey.last_seen_at.asc())
                    .limit(self.BATCH)
                )
            ).scalars().all()
            if not pending:
                return
            touched = 0
            for journey in pending:
                try:
                    touched += await process_journey(
                        db, journey, tz_name=tz_name, min_days=min_days
                    )
                except Exception:
                    logger.exception(
                        "associating journey %s failed", journey.id
                    )
                # Stamped even on failure. A journey that cannot be folded
                # would otherwise be retried on every tick forever, and the
                # evidence it carries is not worth a permanent hot loop.
                journey.associations_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(
                "associator folded %d journeys, touched %d edges",
                len(pending), touched,
            )
