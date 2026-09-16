"""Household mode (#184): home, away, night.

The mode is one setting the rule engine reads once per tick. A rule with
``conditions.modes`` fires only while the house is in one of those modes;
a rule without that key fires in every mode, which is every rule written
before this existed. These tests cover the pure helpers, the engine gate,
the API that changes the mode, and the places that report it.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import shared.app_settings as app_settings
from services.api.main import app
from shared.auth import get_current_user
from shared.database import get_db
from shared.household_mode import (
    DEFAULT_MODE,
    MODE_HINTS,
    MODE_LABELS,
    MODES,
    is_mode,
    normalize_modes,
    rule_active_in,
)
from tests._engine_helpers import FakeRule, install_engine


# ── pure helpers ────────────────────────────────────────────────────


def test_every_mode_has_a_label_and_a_hint():
    for m in MODES:
        assert MODE_LABELS[m] and MODE_LABELS[m] != m
        assert MODE_HINTS[m]


def test_default_mode_is_a_real_mode():
    assert is_mode(DEFAULT_MODE)


@pytest.mark.parametrize("bad", [None, "", "AWAY", "vacation", 3, ["away"]])
def test_is_mode_rejects_anything_not_in_the_list(bad):
    assert not is_mode(bad)


def test_a_rule_without_modes_is_active_in_every_mode():
    for m in MODES:
        assert rule_active_in(None, m)
        assert rule_active_in({}, m)
        assert rule_active_in({"modes": []}, m)
        assert rule_active_in({"camera_id": "x"}, m)


def test_a_rule_with_modes_is_active_only_in_those():
    cond = {"modes": ["away", "night"]}
    assert rule_active_in(cond, "away")
    assert rule_active_in(cond, "night")
    assert not rule_active_in(cond, "home")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ([], None),
        ("away", ["away"]),
        (["away", "AWAY", " night "], ["away", "night"]),
        (["vacation"], None),
        (["away", "vacation"], ["away"]),
        (42, None),
    ],
)
def test_normalize_modes(raw, expected):
    assert normalize_modes(raw) == expected


# ── the engine gate ─────────────────────────────────────────────────


def _set_mode(monkeypatch, mode):
    async def fake_get_setting(key, default=None):
        if key == "household_mode":
            return mode
        return default

    monkeypatch.setattr(app_settings, "get_setting", fake_get_setting)


def test_rule_gated_on_away_is_quiet_while_home(monkeypatch):
    rule = FakeRule(
        name="door while out",
        trigger_pattern={"type": "any"},
        conditions={"modes": ["away"]},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _set_mode(monkeypatch, "home")
    asyncio.run(eng.evaluate({"camera_id": str(uuid.uuid4())}))
    assert rec.call_count == 0


def test_rule_gated_on_away_fires_once_the_house_is_away(monkeypatch):
    rule = FakeRule(
        name="door while out",
        trigger_pattern={"type": "any"},
        conditions={"modes": ["away"]},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _set_mode(monkeypatch, "away")
    asyncio.run(eng.evaluate({"camera_id": str(uuid.uuid4())}))
    assert rec.call_count == 1


def test_the_mode_is_read_fresh_every_tick(monkeypatch):
    """Coming home has to silence the rule on the next frame, not after a
    restart."""
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        conditions={"modes": ["away"]},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _set_mode(monkeypatch, "away")
    asyncio.run(eng.evaluate({}))
    _set_mode(monkeypatch, "home")
    asyncio.run(eng.evaluate({}))
    _set_mode(monkeypatch, "night")
    asyncio.run(eng.evaluate({}))
    assert rec.call_count == 1


def test_rules_without_modes_are_untouched_by_the_mode(monkeypatch):
    """Every rule that existed before #184 keeps firing in every mode."""
    rule = FakeRule(name="r", trigger_pattern={"type": "any"}, cooldown_seconds=0)
    eng, rec = install_engine(monkeypatch, [rule])
    for m in MODES:
        _set_mode(monkeypatch, m)
        asyncio.run(eng.evaluate({}))
    assert rec.call_count == len(MODES)


def test_a_broken_settings_read_falls_back_to_home(monkeypatch):
    """A settings outage must never arm anything by accident. Home is the
    quiet default, so falling back there fails closed."""
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        conditions={"modes": ["away"]},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])

    async def boom(key, default=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(app_settings, "get_setting", boom)
    asyncio.run(eng.evaluate({}))
    assert rec.call_count == 0


def test_a_garbage_mode_value_falls_back_to_home(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        conditions={"modes": ["away"]},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    _set_mode(monkeypatch, "vacation")
    asyncio.run(eng.evaluate({}))
    assert rec.call_count == 0


def test_legacy_callers_that_pass_no_mode_are_not_gated():
    """POST /rules/replay and older code call _check_conditions without a
    mode. That must mean "do not gate", not "assume home"."""
    from services.events.engine import RuleEngine

    assert RuleEngine._check_conditions({"modes": ["away"]}, {}, None)


# ── the API ─────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _FakeDb:
    """Enough of AsyncSession for the household router: it selects rule
    conditions, selects history, and adds one row on change."""

    def __init__(self, rules=()):
        self.rules = list(rules)
        self.history = []
        self.added = []

    async def execute(self, stmt):
        text = str(stmt)
        if "rules" in text:
            return _FakeResult([(c,) for c in self.rules])
        return _FakeResult(
            [(h, "Sam") for h in sorted(self.history, key=lambda h: h.changed_at, reverse=True)]
        )

    def add(self, row):
        row.id = row.id or uuid.uuid4()
        self.added.append(row)
        self.history.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        pass


def _client(monkeypatch, db, mode="home"):
    store = {"household_mode": mode}

    async def fake_get(key, default=None):
        return store.get(key, default)

    async def fake_set(key, value):
        store[key] = value

    import services.api.routes.household as household

    monkeypatch.setattr(household, "get_setting", fake_get)
    monkeypatch.setattr(household, "set_setting", fake_set)

    user = SimpleNamespace(id=uuid.uuid4(), display_name="Sam")
    app.dependency_overrides[get_current_user] = lambda: user

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), store, user


def _teardown():
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def test_get_mode_reports_the_current_mode_and_the_vocabulary(monkeypatch):
    client, _, _ = _client(monkeypatch, _FakeDb(), mode="night")
    try:
        r = client.get("/api/household/mode")
    finally:
        _teardown()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "night"
    assert [m["key"] for m in body["modes"]] == list(MODES)
    for m in body["modes"]:
        assert m["label"] == MODE_LABELS[m["key"]]
        assert m["hint"] == MODE_HINTS[m["key"]]


def test_get_mode_counts_the_rules_the_mode_silences(monkeypatch):
    db = _FakeDb(rules=[{"modes": ["away"]}, {"modes": ["away", "night"]}, None, {"camera_id": "x"}])
    client, _, _ = _client(monkeypatch, db, mode="home")
    try:
        r = client.get("/api/household/mode")
    finally:
        _teardown()
    assert r.json()["silenced_rule_count"] == 2


def test_put_mode_changes_the_setting_and_records_who(monkeypatch):
    db = _FakeDb()
    client, store, user = _client(monkeypatch, db, mode="home")
    try:
        r = client.put("/api/household/mode", json={"mode": "away", "note": "off to work"})
    finally:
        _teardown()
    assert r.status_code == 200, r.text
    assert store["household_mode"] == "away"
    assert r.json()["mode"] == "away"
    assert r.json()["source"] == "manual"
    assert len(db.added) == 1
    row = db.added[0]
    assert row.mode == "away"
    assert row.previous_mode == "home"
    assert row.changed_by_user_id == user.id
    assert row.note == "off to work"
    assert r.json()["history"][0]["changed_by_name"] == "Sam"


def test_setting_the_same_mode_twice_writes_no_history(monkeypatch):
    """Tapping the active chip must not litter the timeline."""
    db = _FakeDb()
    client, _, _ = _client(monkeypatch, db, mode="away")
    try:
        r = client.put("/api/household/mode", json={"mode": "away"})
    finally:
        _teardown()
    assert r.status_code == 200
    assert db.added == []


@pytest.mark.parametrize("bad", ["vacation", "Away", "", None])
def test_put_rejects_a_mode_that_does_not_exist(monkeypatch, bad):
    client, store, _ = _client(monkeypatch, _FakeDb(), mode="home")
    try:
        r = client.put("/api/household/mode", json={"mode": bad})
    finally:
        _teardown()
    assert r.status_code == 422
    assert store["household_mode"] == "home"


# ── the places that report the mode ─────────────────────────────────


def test_the_away_starter_is_gated_on_away_and_night():
    from shared.rule_starters import starter_rule

    rule = starter_rule("someone-at-the-door-while-out", str(uuid.uuid4()))
    assert rule is not None
    assert rule["conditions"]["modes"] == ["away", "night"]
    assert rule["actions"][0]["type"] == "notify"


def test_the_plain_door_starter_stays_ungated():
    """It is the first alert a new household sees, and they are standing
    at home when they test it."""
    from shared.rule_starters import starter_rule

    rule = starter_rule("someone-at-the-door", str(uuid.uuid4()))
    assert not (rule["conditions"] or {}).get("modes")


def test_rule_test_explains_a_mode_block(monkeypatch):
    from services.api.routes.rules import _explain_outcome

    reason = _explain_outcome(
        True, False, {"type": "object_detected", "label": "person"},
        {"modes": ["away"]}, {}, None, mode="home",
    )
    assert "Away" in reason and "Home" in reason
    assert "blocked" in reason.lower()
