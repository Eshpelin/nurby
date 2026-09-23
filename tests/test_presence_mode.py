"""Auto Home/Away mode from the identity graph (#184)."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.perception import presence_mode as pm

# ── decide_mode (pure) ──

def _decide(**kw):
    base = dict(
        current_mode="home", member_count=2, present_count=1,
        latest_source=None, seconds_since_change=None,
    )
    base.update(kw)
    return pm.decide_mode(**base)


def test_no_members_is_inert():
    assert _decide(member_count=0, present_count=0, current_mode="home") is None


def test_everyone_gone_goes_away():
    assert _decide(present_count=0, current_mode="home") == "away"


def test_already_away_stays_away():
    assert _decide(present_count=0, current_mode="away") is None


def test_arrival_while_away_goes_home():
    assert _decide(present_count=1, current_mode="away") == "home"


def test_present_while_home_no_change():
    assert _decide(present_count=2, current_mode="home") is None


def test_night_is_never_touched():
    assert _decide(present_count=0, current_mode="night") is None
    assert _decide(present_count=1, current_mode="night") is None


def test_recent_manual_change_is_respected():
    # Manually set home 2 min ago; even though nobody is seen, don't flip yet.
    assert _decide(present_count=0, current_mode="home",
                   latest_source="manual", seconds_since_change=120) is None
    # After the grace window, presence takes over.
    assert _decide(present_count=0, current_mode="home",
                   latest_source="manual", seconds_since_change=3600) == "away"


def test_auto_source_is_not_graced():
    # A prior auto change does not block a further auto change.
    assert _decide(present_count=0, current_mode="home",
                   latest_source="auto", seconds_since_change=1) == "away"


# ── evaluate_and_apply (integration with a mock db) ──

class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _DB:
    def __init__(self, member_ids, observations, latest_change):
        self.member_ids = member_ids
        self.observations = observations
        self.latest_change = latest_change

    async def execute(self, stmt):
        t = str(stmt).lower()
        if "from persons" in t:
            return _Res(list(self.member_ids))
        if "from observations" in t:
            return _Res(self.observations)
        if "from household_mode_changes" in t:
            return _Res([self.latest_change] if self.latest_change else [])
        return _Res([])


@pytest.mark.asyncio
async def test_evaluate_applies_away_when_nobody_seen(monkeypatch):
    member = uuid.uuid4()
    db = _DB(member_ids=[member], observations=[], latest_change=None)

    async def _get_setting(key, default=None):
        return "home"

    applied = {}

    async def _change_mode(db, *, mode, source, user_id, note):
        applied["mode"] = mode
        applied["source"] = source

    monkeypatch.setattr("shared.app_settings.get_setting", _get_setting)
    monkeypatch.setattr("services.api.routes.household.change_mode", _change_mode)

    out = await pm.evaluate_and_apply(db, now=datetime.now(timezone.utc))
    assert out == "away"
    assert applied == {"mode": "away", "source": "auto"}


@pytest.mark.asyncio
async def test_evaluate_applies_home_on_arrival(monkeypatch):
    member = uuid.uuid4()
    now = datetime.now(timezone.utc)
    obs = {"faces": [{"person_id": str(member)}]}
    db = _DB(member_ids=[member], observations=[obs], latest_change=None)

    async def _get_setting(key, default=None):
        return "away"

    applied = {}

    async def _change_mode(db, *, mode, source, user_id, note):
        applied["mode"] = mode

    monkeypatch.setattr("shared.app_settings.get_setting", _get_setting)
    monkeypatch.setattr("services.api.routes.household.change_mode", _change_mode)

    out = await pm.evaluate_and_apply(db, now=now)
    assert out == "home"
    assert applied["mode"] == "home"


@pytest.mark.asyncio
async def test_evaluate_inert_without_members(monkeypatch):
    db = _DB(member_ids=[], observations=[], latest_change=None)
    called = {"n": 0}

    async def _change_mode(db, **kw):
        called["n"] += 1

    monkeypatch.setattr("services.api.routes.household.change_mode", _change_mode)
    out = await pm.evaluate_and_apply(db, now=datetime.now(timezone.utc))
    assert out is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_evaluate_respects_recent_manual(monkeypatch):
    member = uuid.uuid4()
    now = datetime.now(timezone.utc)
    latest = SimpleNamespace(source="manual", changed_at=now - timedelta(minutes=2))
    db = _DB(member_ids=[member], observations=[], latest_change=latest)

    async def _get_setting(key, default=None):
        return "home"

    called = {"n": 0}

    async def _change_mode(db, **kw):
        called["n"] += 1

    monkeypatch.setattr("shared.app_settings.get_setting", _get_setting)
    monkeypatch.setattr("services.api.routes.household.change_mode", _change_mode)

    out = await pm.evaluate_and_apply(db, now=now)
    assert out is None  # manual set 2 min ago wins
    assert called["n"] == 0
