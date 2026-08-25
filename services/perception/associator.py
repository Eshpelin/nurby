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


def fold(assoc: EntityAssociation, when: datetime, tz_name: str, min_days: int) -> bool:
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


def vehicles_in(observations) -> dict[str, str | None]:
    """``{vehicle_id: label}`` for vehicles identified in observations.

    Only vehicles that resolved to a Vehicle row count. An unmatched
    detection is a box around something car-shaped, which is not an
    identity and cannot carry an association. Pure, for tests.
    """
    out: dict[str, str | None] = {}
    for obs in observations or []:
        payload = getattr(obs, "vehicle_detections", None) or {}
        for entry in payload.get("vehicles") or []:
            vid = entry.get("vehicle_id")
            if not vid:
                continue
            out.setdefault(str(vid), entry.get("identity_key"))
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

    if not fold(existing, when, tz_name, min_days):
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

    touched = 0
    for vehicle_id, identity_key in vehicles_in(rows).items():
        label = identity_key
        try:
            vehicle = await db.get(Vehicle, uuid.UUID(vehicle_id))
            if vehicle is not None:
                label = vehicle.nickname or vehicle.display_name or identity_key
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
        )
        if edge is not None:
            touched += 1
    return touched


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

    async def _tick(self) -> None:
        if not bool(await get_setting("associations_enabled", True)):
            return
        tz_name = await get_setting("system_timezone") or "UTC"
        min_days = int(
            await get_setting("association_min_distinct_days", DEFAULT_MIN_DISTINCT_DAYS)
        )
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
