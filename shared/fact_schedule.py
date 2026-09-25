"""When a household note's schedule is in force (issue #185).

A note like "the cleaner comes Thursdays 9-11" can, after a person
explicitly confirms it, mute matching alerts during that window. The
matching itself lives here so the rule engine, the API and the tests all
agree on one answer.

Conventions match the associator's: weekdays are ``date.weekday()``
ints with Monday at 0, and the window is minutes since local midnight,
half-open (start inclusive, end exclusive). An unknown timezone falls
back to the household's effective zone rather than raising -- the same
recovery the associator uses, because a silently-missed suppression is
an alert that should not have fired, and a crash is worse.
"""

from __future__ import annotations

from datetime import datetime

from shared.timezone import effective_timezone_name

# The weekdays a schedule may name, Monday-first. Stored as JSON, which
# round-trips ints fine, but validated here rather than trusted.
WEEKDAYS = set(range(7))

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

MIN_MINUTE = 0
MAX_MINUTE = 24 * 60


def normalize_days(days) -> list[int] | None:
    """Validated, deduplicated, sorted weekday list, or None. Pure.

    None means "no schedule": the note is knowledge, not a timetable.
    Anything outside 0-6 makes the whole schedule invalid rather than
    being silently dropped -- a typo in a weekday is a question for the
    person who wrote it, not something to guess around.
    """
    if days is None:
        return None
    if not isinstance(days, (list, tuple)):
        return None
    cleaned: list[int] = []
    for day in days:
        if isinstance(day, bool) or not isinstance(day, int) or day not in WEEKDAYS:
            return None
        if day not in cleaned:
            cleaned.append(day)
    return sorted(cleaned) or None


def normalize_window(start_minute, end_minute) -> tuple[int, int] | None:
    """Validated half-open ``(start, end)`` window in minutes, or None. Pure.

    The window must be within one local day; a "Thursday 23:00-01:00"
    schedule spans midnight and v1 does not pretend to represent it --
    the API rejects it so nobody believes they armed something that
    never matches.
    """
    for value in (start_minute, end_minute):
        if isinstance(value, bool) or not isinstance(value, int):
            return None
    if not (MIN_MINUTE <= start_minute <= MAX_MINUTE):
        return None
    if not (MIN_MINUTE <= end_minute <= MAX_MINUTE):
        return None
    if end_minute <= start_minute:
        return None
    return start_minute, end_minute


def local_now(when: datetime, tz_name: str | None) -> datetime:
    """``when`` in the schedule's zone (None = household zone)."""
    if tz_name is None:
        return when  # caller resolved the household zone already
    try:
        from zoneinfo import ZoneInfo

        return when.astimezone(ZoneInfo(tz_name))
    except Exception:
        return when


def schedule_active(days, start_minute, end_minute, *, now_local: datetime) -> bool:
    """Whether the schedule covers ``now_local``. Pure.

    ``now_local`` must already be in the schedule's zone; splitting the
    zone resolution from the match keeps this testable without patching
    the clock.
    """
    cleaned = normalize_days(days)
    window = normalize_window(start_minute, end_minute)
    if cleaned is None or window is None:
        return False
    if now_local.weekday() not in cleaned:
        return False
    minute_of_day = now_local.hour * 60 + now_local.minute
    return window[0] <= minute_of_day < window[1]


async def suppression_active(fact, *, now: datetime) -> bool:
    """Whether this fact may mute an alert right now.

    Every gate is deliberate (issue #185):

    - ``status == "established"`` -- archived or rejected notes stop
      working the moment they leave that state, so silencing is always
      one visible toggle away from being undone.
    - ``suppresses_alerts`` and ``suppression_confirmed_at`` -- a person
      armed this on purpose; a learned habit never suppresses on its own.
    - a well-formed schedule that covers now, in household-local time
      (``schedule_tz`` override honored).

    Async only because resolving the household zone is an await; the
    match itself is the pure ``schedule_active``.
    """
    if getattr(fact, "status", None) != "established":
        return False
    if not getattr(fact, "suppresses_alerts", False):
        return False
    if getattr(fact, "suppression_confirmed_at", None) is None:
        return False
    days = getattr(fact, "schedule_days", None)
    start = getattr(fact, "schedule_start_minute", None)
    end = getattr(fact, "schedule_end_minute", None)
    tz_name = getattr(fact, "schedule_tz", None) or await effective_timezone_name()
    return schedule_active(days, start, end, now_local=local_now(now, tz_name))


def suppression_armed(fact) -> bool:
    """Whether suppression is armed at all (regardless of time). Pure.

    Used by the API view layer: the badge "this note can mute alerts"
    should show even outside the window, with the schedule next to it.
    """
    return bool(
        getattr(fact, "suppresses_alerts", False)
        and getattr(fact, "suppression_confirmed_at", None) is not None
        and getattr(fact, "schedule_days", None)
    )


def schedule_summary(fact) -> str | None:
    """A short human rendering of a fact's schedule, or None. Pure."""
    cleaned = normalize_days(getattr(fact, "schedule_days", None))
    window = normalize_window(
        getattr(fact, "schedule_start_minute", None),
        getattr(fact, "schedule_end_minute", None),
    )
    if cleaned is None or window is None:
        return None
    if cleaned == sorted(WEEKDAYS):
        day_part = "daily"
    elif len(cleaned) == 1:
        day_part = WEEKDAY_NAMES[cleaned[0]] + "s"
    else:
        day_part = ", ".join(WEEKDAY_NAMES[d] for d in cleaned)
    start_h, start_m = divmod(window[0], 60)
    end_h, end_m = divmod(window[1], 60)
    return f"{day_part} {start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"
