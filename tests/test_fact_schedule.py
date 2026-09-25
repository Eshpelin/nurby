"""Household-note schedules: when a note is in force (issue #185).

Pure matching first: the suppression answer the rule engine gives has to
be the answer the API, the UI badge and the tests all agree on.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from shared.fact_schedule import (
    normalize_days,
    normalize_window,
    schedule_active,
    schedule_summary,
    suppression_active,
    suppression_armed,
)

# A Thursday, 10:00 local, timezone-naive on purpose: schedule_active
# receives an already-local datetime and does no conversion itself.
THURSDAY_1000 = datetime(2026, 9, 24, 10, 0)  # 2026-09-24 is a Thursday
FRIDAY_1000 = datetime(2026, 9, 25, 10, 0)


def _utc(y, m, d, h, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=timezone.utc)


# ---- normalize_days -------------------------------------------------------


def test_days_normalize_and_dedupe():
    assert normalize_days([3]) == [3]
    assert normalize_days([3, 3, 1]) == [1, 3]
    assert normalize_days([6, 0]) == [0, 6]  # sorted, Monday first


def test_days_reject_out_of_range_and_shapes():
    assert normalize_days(None) is None
    assert normalize_days([]) is None
    assert normalize_days([7]) is None
    assert normalize_days([-1]) is None
    assert normalize_days(["3"]) is None
    assert normalize_days(True) is None  # bool is an int; refuse it anyway
    assert normalize_days("thu") is None


# ---- normalize_window -----------------------------------------------------


def test_window_accepts_half_open_day_bounds():
    assert normalize_window(0, 1440) == (0, 1440)
    assert normalize_window(540, 660) == (540, 660)


def test_window_rejects_midnight_spans_and_garbage():
    assert normalize_window(660, 540) is None  # end before start
    assert normalize_window(540, 540) is None  # empty
    assert normalize_window(-1, 600) is None
    assert normalize_window(600, 1441) is None
    assert normalize_window("9:00", 600) is None
    assert normalize_window(540.0, 600) is None


# ---- schedule_active ------------------------------------------------------


def test_thursday_schedule_matches_thursday_inside_the_window():
    assert schedule_active([3], 540, 660, now_local=THURSDAY_1000) is True


def test_schedule_does_not_match_other_weekdays():
    assert schedule_active([3], 540, 660, now_local=FRIDAY_1000) is False


def test_window_edges_are_start_inclusive_end_exclusive():
    start = datetime(2026, 9, 24, 9, 0)
    last = datetime(2026, 9, 24, 10, 59)
    end = datetime(2026, 9, 24, 11, 0)
    for moment in (start, last):
        assert schedule_active([3], 540, 660, now_local=moment) is True
    assert schedule_active([3], 540, 660, now_local=end) is False


def test_invalid_schedule_never_matches():
    # A malformed schedule answers False everywhere rather than raising:
    # a corrupt row must not disable rule evaluation.
    assert schedule_active(None, 540, 660, now_local=THURSDAY_1000) is False
    assert schedule_active([3], None, 660, now_local=THURSDAY_1000) is False
    assert schedule_active([9], 540, 660, now_local=THURSDAY_1000) is False


# ---- suppression gates ----------------------------------------------------


def _fact(**kw):
    base = dict(
        id=uuid.uuid4(),
        status="established",
        suppresses_alerts=True,
        suppression_confirmed_at=_utc(2026, 9, 1, 0),
        schedule_days=[3],
        schedule_start_minute=540,
        schedule_end_minute=660,
        schedule_tz=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_all_gates_required_for_suppression():
    import asyncio

    def _run(coro):
        return asyncio.run(coro)

    now = _utc(2026, 9, 24, 10)  # Thursday 10:00 UTC
    # Fully armed + in window (UTC fallback zone), suppresses.
    assert _run(suppression_active(_fact(), now=now)) is True
    # Not established: archived or rejected notes stop mattering.
    assert _run(suppression_active(_fact(status="archived"), now=now)) is False
    assert _run(suppression_active(_fact(status="rejected"), now=now)) is False
    # Never confirmed: a learned habit cannot mute anything on its own.
    assert _run(suppression_active(_fact(suppression_confirmed_at=None), now=now)) is False
    assert _run(suppression_active(_fact(suppresses_alerts=False), now=now)) is False
    # Outside the window.
    assert _run(suppression_active(_fact(), now=_utc(2026, 9, 24, 12))) is False
    # Wrong weekday entirely.
    assert _run(suppression_active(_fact(), now=_utc(2026, 9, 25, 10))) is False


def test_armed_badge_and_summary():
    armed = _fact()
    assert suppression_armed(armed) is True
    assert suppression_armed(_fact(suppression_confirmed_at=None)) is False
    assert schedule_summary(armed) == "Thursdays 09:00-11:00"


def test_summary_handles_daily_and_multi_day():
    every_day = _fact(schedule_days=[0, 1, 2, 3, 4, 5, 6])
    assert schedule_summary(every_day).startswith("daily")
    weekend = _fact(schedule_days=[5, 6])
    assert schedule_summary(weekend) == "Saturday, Sunday 09:00-11:00"
    assert schedule_summary(_fact(schedule_days=None)) is None
