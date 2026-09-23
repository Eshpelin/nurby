"""Auto Home/Away mode from the identity graph (#184).

Household mode (home / away / night) already exists as a setting + history,
and rules opt into modes via ``conditions.modes``. What was missing is the
presence detector the module docstring in ``shared/household_mode.py`` calls
out as "does not exist yet": flipping the mode automatically when the people
Nurby knows leave or come back.

Signal: the named persons flagged ``is_household_member`` and when each was
last seen (from ``person_detections`` on recent observations, the same data
People/Journeys use). Decision, kept pure in :func:`decide_mode` so it is
unit-testable:

* Nobody known seen for a while  -> everyone is out    -> ``away``.
* A known member seen again while away -> someone is back -> ``home``.

Auto only ever toggles home<->away. It never touches ``night`` (a manual /
scheduled choice), and it holds off briefly after any manual change so a tap
is not immediately overridden. It is inert until at least one person is
marked a household member, so it cannot surprise an install that never opted
in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Observation, Person

# Seen within this window counts as "present".
HOME_WINDOW_MINUTES = 15
# Don't auto-override a manual/agent change for this long, so a deliberate tap
# (or an Ask instruction) sticks before presence takes back over.
MANUAL_GRACE_MINUTES = 10


def decide_mode(
    *,
    current_mode: str,
    member_count: int,
    present_count: int,
    latest_source: str | None,
    seconds_since_change: float | None,
    grace_minutes: int = MANUAL_GRACE_MINUTES,
) -> str | None:
    """Return the mode auto-presence wants, or ``None`` to leave it alone.

    Pure. See the module docstring for the policy.
    """
    if member_count <= 0:
        return None  # feature dormant until a household is defined
    if current_mode == "night":
        return None  # never fight a manual/scheduled night
    # Respect a recent manual/agent choice.
    if (
        latest_source in ("manual", "agent")
        and seconds_since_change is not None
        and seconds_since_change < grace_minutes * 60
    ):
        return None
    if present_count == 0 and current_mode != "away":
        return "away"
    if present_count >= 1 and current_mode == "away":
        return "home"
    return None


async def _present_member_count(db: AsyncSession, member_ids: set, now: datetime) -> int:
    """How many flagged members were seen within the home window."""
    if not member_ids:
        return 0
    cutoff = now - timedelta(minutes=HOME_WINDOW_MINUTES)
    rows = (
        await db.execute(
            select(Observation.person_detections)
            .where(Observation.person_detections.isnot(None))
            .where(Observation.started_at >= cutoff)
            .order_by(Observation.started_at.desc())
            .limit(500)
        )
    ).scalars().all()
    seen: set = set()
    wanted = {str(m) for m in member_ids}
    for pd in rows:
        for face in (pd or {}).get("faces", []) or []:
            pid = face.get("person_id")
            if pid and str(pid) in wanted:
                seen.add(str(pid))
        if len(seen) == len(wanted):
            break
    return len(seen)


async def evaluate_and_apply(db: AsyncSession, now: datetime | None = None) -> str | None:
    """Compute presence and apply an auto mode change if warranted.

    Returns the new mode when it changed, else ``None``. Uses the same
    ``change_mode`` the API uses, tagged ``source="auto"``.
    """
    now = now or datetime.now(timezone.utc)
    from shared.app_settings import get_setting
    from shared.household_mode import DEFAULT_MODE
    from shared.models import HouseholdModeChange

    member_ids = set(
        (await db.execute(select(Person.id).where(Person.is_household_member.is_(True)))).scalars().all()
    )
    if not member_ids:
        return None

    present = await _present_member_count(db, member_ids, now)
    current = await get_setting("household_mode") or DEFAULT_MODE

    latest = (
        await db.execute(
            select(HouseholdModeChange).order_by(HouseholdModeChange.changed_at.desc()).limit(1)
        )
    ).scalars().first()
    latest_source = latest.source if latest else None
    since = None
    if latest and latest.changed_at:
        changed_at = latest.changed_at
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        since = (now - changed_at).total_seconds()

    target = decide_mode(
        current_mode=current,
        member_count=len(member_ids),
        present_count=present,
        latest_source=latest_source,
        seconds_since_change=since,
    )
    if target is None or target == current:
        return None

    # Reuse the API's setter so history + settings stay consistent.
    from services.api.routes.household import change_mode

    note = "nobody home" if target == "away" else "someone arrived"
    await change_mode(db, mode=target, source="auto", user_id=None, note=note)
    return target
