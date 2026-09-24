"""Expected-activity absence-alert scheduler (#215).

Covers the pure scheduling decisions (due / window bounds / mode gating) and
the evaluate_one flow: a covered empty window fires one alert, a satisfied
window fires none, a coverage gap reads unknown (never violated), and an
away-scoped expectation is skipped while away.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.perception import expected_activity_sweeper as sw


def _exp(**kw):
    base = dict(
        id=uuid.uuid4(), name="Mom to kitchen", subject_kind="person",
        subject_key="Mom", camera_ids=[], weekdays=[0, 1, 2, 3, 4],
        start_time="09:00", end_time="10:00", grace_minutes=30,
        active_modes=None, enabled=True, last_evaluated_on=None, last_status=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# A Monday for deterministic weekday math.
MON_UTC = datetime(2026, 6, 8, 0, 0, tzinfo=timezone.utc)


def _at(hh, mm=0):
    return MON_UTC.replace(hour=hh, minute=mm)


# ── due() ──

def test_not_due_before_deadline():
    exp = _exp(weekdays=[0])
    assert sw.due(exp, _at(10, 15)) is False  # window 09-10, grace 30 -> 10:30


def test_due_after_deadline():
    exp = _exp(weekdays=[0])
    assert sw.due(exp, _at(10, 45)) is True


def test_not_due_wrong_weekday():
    exp = _exp(weekdays=[5, 6])  # weekend only
    assert sw.due(exp, _at(23, 0)) is False


def test_not_due_when_already_evaluated_today():
    exp = _exp(weekdays=[0], last_evaluated_on="2026-06-08")
    assert sw.due(exp, _at(11, 0)) is False


def test_not_due_when_disabled():
    exp = _exp(weekdays=[0], enabled=False)
    assert sw.due(exp, _at(11, 0)) is False


def test_overnight_window_bounds():
    exp = _exp(start_time="22:00", end_time="06:00")
    start, end = sw._window_bounds(exp, _at(23, 0))
    assert start.hour == 22 and end.hour == 6
    assert end.date() > start.date()  # rolls to next day


def test_mode_ok():
    assert sw._mode_ok(_exp(active_modes=None), "away") is True
    assert sw._mode_ok(_exp(active_modes=["home", "night"]), "home") is True
    assert sw._mode_ok(_exp(active_modes=["home", "night"]), "away") is False


# ── evaluate_one ──

class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, obs):
        self._obs = obs
        self.added = []
        self.committed = 0

    def add(self, o):
        self.added.append(o)

    async def commit(self):
        self.committed += 1

    async def execute(self, stmt):
        return _Res(self._obs)


def _obs(cam, hh, mm=30):
    return SimpleNamespace(camera_id=cam, started_at=_at(hh, mm), person_detections={})


@pytest.fixture
def no_gaps(monkeypatch):
    async def _cov(db, **kw):
        return {"cameras": [{"camera_id": "c1", "evidence_state": "active", "gaps": []}]}
    monkeypatch.setattr("services.perception.coverage.compute_coverage", _cov)


@pytest.fixture
def with_gap(monkeypatch):
    async def _cov(db, **kw):
        return {"cameras": [{"camera_id": "c1", "evidence_state": "outage", "gaps": ["offline"]}]}
    monkeypatch.setattr("services.perception.coverage.compute_coverage", _cov)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_violated_fires_one_alert(no_gaps):
    exp = _exp(weekdays=[0])
    db = _DB(obs=[])  # nothing seen in the window
    status = _run(sw.evaluate_one(db, exp, timezone.utc, "home", _at(11, 0)))
    assert status == "violated"
    assert exp.last_status == "violated"
    assert exp.last_evaluated_on == "2026-06-08"
    assert len(db.added) == 1 and db.added[0].severity == "alert"


def test_satisfied_fires_nothing(no_gaps):
    exp = _exp(weekdays=[0])
    db = _DB(obs=[_obs("c1", 9, 30)])  # Mom seen in the window
    status = _run(sw.evaluate_one(db, exp, timezone.utc, "home", _at(11, 0)))
    assert status == "satisfied"
    assert db.added == []


def test_coverage_gap_is_unknown_not_violated(with_gap):
    exp = _exp(weekdays=[0])
    db = _DB(obs=[])
    status = _run(sw.evaluate_one(db, exp, timezone.utc, "home", _at(11, 0)))
    assert status == "unknown"
    assert db.added == []  # never alert when the window was not fully covered


def test_skipped_when_mode_excluded(no_gaps):
    exp = _exp(weekdays=[0], active_modes=["home", "night"])
    db = _DB(obs=[])
    status = _run(sw.evaluate_one(db, exp, timezone.utc, "away", _at(11, 0)))
    assert status == "skipped_mode"
    assert db.added == []
    assert exp.last_status == "skipped_mode"


def test_not_due_returns_none(no_gaps):
    exp = _exp(weekdays=[0])
    db = _DB(obs=[])
    assert _run(sw.evaluate_one(db, exp, timezone.utc, "home", _at(9, 30))) is None
