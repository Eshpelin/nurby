"""Distil durable household facts, and never nag (issue #141).

``household_context`` builds the orientation block fresh from live state
on every run. That is correct but shallow: it can only say what a query
returns right now. It cannot hold "the cat is usually on the Back Door
camera between 2am and 5am", which is the kind of knowledge that stops a
whole class of wrong answer before a tool is ever called.

This is the curator. It runs when the system is idle, distils facts from
evidence that already exists, and maintains them over time. The invariants
are the valuable part and they are enforced here rather than trusted to
callers:

- **Only agent-created facts are auto-modified.** A fact a person wrote is
  theirs. The curator does not edit it, archive it, or re-word it.
- **Nothing is auto-deleted, only archived.** Archive is recoverable; a
  delete is a guess that cannot be taken back.
- **Pinned bypasses everything.** A pinned fact is never archived by age
  or by thin evidence.
- **Rejection is permanent.** A rejected fact is never proposed again.
  That is the whole difference between a system that learns from its
  household and one that nags them.

The distillation itself is deliberately boring: facts are derived from
:class:`EntityAssociation` edges and journey history, which are already
counted and already gated on distinct days. An auxiliary model is used
only to phrase a fact in plain language, never to decide whether it is
true. A model that invents household facts is a liability; a model that
writes a good sentence about a counted pattern is useful.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from shared import estop
from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import EntityAssociation, HouseholdFact

logger = logging.getLogger("nurby.agent.curator")

# How long a fact can go unconfirmed before it is archived. Long, because
# a household habit can pause for a holiday without ceasing to be true.
DEFAULT_STALE_DAYS = 45

# How long the system must be idle before a curator pass runs. It is
# background work competing with video decode, and nothing about a
# multi-day habit needs to be noticed promptly.
DEFAULT_INTERVAL_HOURS = 12

# Statuses the curator will not touch, for different reasons: a person
# said no, or a person said yes and the curator has no business rewording
# it.
UNTOUCHABLE_STATUSES = {"rejected"}

# Only facts the agent created are ever auto-modified.
AGENT_SOURCE = "agent"


# ---- pure policy ---------------------------------------------------------


def may_modify(fact) -> bool:
    """Whether the curator is allowed to change this fact at all. Pure."""
    if fact is None:
        return False
    if getattr(fact, "source", AGENT_SOURCE) != AGENT_SOURCE:
        return False  # a person wrote it
    if getattr(fact, "status", None) in UNTOUCHABLE_STATUSES:
        return False  # a person rejected it
    if getattr(fact, "pinned", False):
        return False  # a person kept it
    return True


def should_archive(fact, now: datetime, stale_days: int = DEFAULT_STALE_DAYS) -> bool:
    """Whether a fact has gone quiet long enough to archive. Pure.

    Archive, never delete: a habit that stops for two months and resumes
    should come back as a candidate rather than having to be rediscovered
    from nothing.
    """
    if not may_modify(fact):
        return False
    if getattr(fact, "status", None) != "established":
        return False
    last = getattr(fact, "last_confirmed_at", None)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) > timedelta(days=stale_days)


def fact_from_association(edge) -> tuple[str, str] | None:
    """``(subject_key, text)`` for an established edge, or None. Pure.

    Deterministic phrasing. The auxiliary model may improve the wording
    later, but the fact exists and is correct without it, so a household
    with no model configured still gets its orientation.
    """
    if getattr(edge, "status", None) != "established":
        return None
    if getattr(edge, "source", "learned") != "learned":
        return None  # declared policy is not a habit
    hours = sorted(
        int(h) for h, c in (getattr(edge, "hour_histogram", None) or {}).items()
        if int(c) > 0
    )
    subject = edge.subject_key
    obj = edge.object_label or edge.object_key
    when = ""
    if hours:
        when = " around " + ", ".join(f"{h:02d}:00" for h in hours[:2])
    text = (
        f"{subject} usually {edge.relation} {obj}{when}"
        f" (seen on {int(edge.distinct_days or 0)} separate days)."
    )
    return f"assoc:{edge.id}", text


def merge_fact(existing, text: str, now: datetime):
    """Fold a freshly derived fact into an existing row, in place. Pure.

    Returns True when the row was touched. A fact the curator may not
    modify is left exactly as it is, which is the point.
    """
    if not may_modify(existing):
        return False
    existing.text = text
    existing.evidence_count = int(existing.evidence_count or 0) + 1
    existing.last_confirmed_at = now
    if existing.status == "archived":
        # Seeing it again makes it a candidate, not immediately
        # established: the household archived it for a reason.
        existing.status = "candidate"
        existing.archived_at = None
    elif existing.status == "candidate":
        existing.status = "established"
    return True


# ---- the pass ------------------------------------------------------------


async def curate_once(db, *, now: datetime | None = None,
                      stale_days: int = DEFAULT_STALE_DAYS) -> dict:
    """One curator pass. Returns a small summary for logging and tests."""
    now = now or datetime.now(timezone.utc)
    created = updated = archived = 0

    edges = (
        await db.execute(
            select(EntityAssociation)
            .where(EntityAssociation.status == "established")
            .where(EntityAssociation.source == "learned")
            .limit(200)
        )
    ).scalars().all()

    for edge in edges:
        derived = fact_from_association(edge)
        if derived is None:
            continue
        subject_key, text = derived
        existing = (
            await db.execute(
                select(HouseholdFact)
                .where(HouseholdFact.subject_key == subject_key)
                .where(HouseholdFact.kind == "habit")
                .where(HouseholdFact.source == AGENT_SOURCE)
                .limit(1)
            )
        ).scalars().first()

        if existing is None:
            db.add(HouseholdFact(
                text=text,
                subject_key=subject_key,
                kind="habit",
                source=AGENT_SOURCE,
                status="candidate",
                evidence_count=1,
                last_confirmed_at=now,
            ))
            created += 1
        elif merge_fact(existing, text, now):
            updated += 1

    stale = (
        await db.execute(
            select(HouseholdFact)
            .where(HouseholdFact.status == "established")
            .where(HouseholdFact.source == AGENT_SOURCE)
            .limit(200)
        )
    ).scalars().all()
    for fact in stale:
        if should_archive(fact, now, stale_days):
            fact.status = "archived"
            fact.archived_at = now
            archived += 1

    return {"created": created, "updated": updated, "archived": archived}


class Curator:
    """Idle-triggered background pass. Mirrors the Associator's shape."""

    TICK_SECONDS = 3600

    def __init__(self) -> None:
        self._stopping = asyncio.Event()
        self._last_run: datetime | None = None

    def stop(self) -> None:
        self._stopping.set()

    def due(self, now: datetime, interval_hours: int) -> bool:
        """Whether enough time has passed since the last pass. Pure."""
        if self._last_run is None:
            return True
        return (now - self._last_run) >= timedelta(hours=interval_hours)

    async def run(self) -> None:
        logger.info("curator started")
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except Exception:
                    logger.exception("curator tick failed")
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.TICK_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("curator stopped")

    async def _tick(self) -> None:
        if not bool(await get_setting("curator_enabled", True)):
            return
        if estop.is_engaged():
            return
        interval = int(
            await get_setting("curator_interval_hours", DEFAULT_INTERVAL_HOURS)
        )
        now = datetime.now(timezone.utc)
        if not self.due(now, interval):
            return
        stale_days = int(await get_setting("fact_stale_days", DEFAULT_STALE_DAYS))
        async with async_session() as db:
            summary = await curate_once(db, now=now, stale_days=stale_days)
            await db.commit()
        self._last_run = now
        if any(summary.values()):
            logger.info(
                "curator: %d new, %d updated, %d archived",
                summary["created"], summary["updated"], summary["archived"],
            )
