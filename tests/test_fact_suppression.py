"""Household-note alert suppression end to end at service level (#185).

The done-when for #185: telling Nurby once that the cleaner comes
Thursdays stops Thursday alerts, and shows up as an explanation in that
day's recap. These tests walk that path without Postgres: the confirm
card becomes a real created note, the rule engine resolves its schedule
and silences subject-bearing alerts, and the digest prompt carries the
explanation.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from services.agent.tools import setup_tools as st
from services.api.routes import household as hh
from shared.fact_schedule import schedule_active


def _run(coro):
    return asyncio.run(coro)


# ---- stubs ----------------------------------------------------------------


class _SessionCtx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *args):
        return False


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return _Scalars(self._rows)


class _Db:
    """Routes canned rows by table name; counts transactions."""

    def __init__(self, fact_rows=(), person_rows=(), assoc_rows=()):
        self.fact_rows = list(fact_rows)
        self.person_rows = list(person_rows)
        self.assoc_rows = list(assoc_rows)
        self.updates = 0
        self.added = []

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        if "update household_facts" in sql:
            self.updates += 1
            return _Result([])
        if "from persons" in sql:
            return _Result(self.person_rows)
        if "from entity_associations" in sql:
            return _Result(self.assoc_rows)
        # The suppression resolver's fact select, and anything else.
        return _Result(self.fact_rows)

    async def commit(self):
        pass

    def add(self, o):
        self.added.append(o)

    async def refresh(self, o):
        pass


# ---- the note the household confirmed -------------------------------------


def _confirmed_note(**kw):
    """The row POST /api/household/facts creates for the cleaner note."""
    import services.api.routes.household as hh_mod

    created = _run(hh_mod.create_fact(
        hh_mod.FactCreate(
            text="the cleaner comes Thursdays and has a key",
            schedule=hh_mod.ScheduleBody(days=[3], start_minute=540, end_minute=660),
            suppress_alerts=True,
            via="agent_chat",
        ),
        SimpleNamespace(id=uuid.uuid4(), role="admin"),
        _Db(),  # commit/refresh no-ops; the handler builds the real row
    ))
    return created


# The API handler returns a view dict; the engine resolves real rows. This
# shim gives back one row-like object with the same fields.
def _note_row(view, entity_kind="person", entity_key="Cleaner"):
    return SimpleNamespace(
        # A stubbed db never flushes, so the id default may not have fired.
        id=view["id"] if view["id"] in (None, "None") else uuid.UUID(view["id"]),
        status="established",
        suppresses_alerts=view["suppresses_alerts"],
        suppression_confirmed_at=datetime.now(timezone.utc),
        entity_kind=entity_kind,
        entity_key=entity_key,
        schedule_days=[3],
        schedule_start_minute=540,
        schedule_end_minute=660,
    )


# ---- remember tool: the structured proposal -------------------------------


def test_remember_proposes_a_schedule_note_for_confirmation():
    db = _Db()
    out = _run(st.remember(
        {"db": db, "user": None},
        fact="the cleaner comes Thursdays 9-11",
        days=[3], start_time="9:00", end_time="11:00",
    ))
    assert out["ok"] is True
    body = out["client_action"]["body"]
    assert body["schedule"] == {"days": [3], "start_minute": 540, "end_minute": 660}
    assert body["suppress_alerts"] is True
    assert "mute" in out["message_for_user"].lower()
    # still a confirm gate: nothing is written by the tool itself
    assert out["client_action"]["method"] == "POST"


def test_remember_rejects_an_inverted_window():
    out = _run(st.remember(
        {"db": _Db(), "user": None},
        fact="night visits", days=[3], start_time="23:00", end_time="05:00",
    ))
    assert out["ok"] is False and "after" in out["error"]


# ---- engine: the confirmed note silences the intended alerts --------------


@pytest.fixture()
def suppression_engine(monkeypatch):
    """An engine whose fact lookup returns one confirmed cleaner note."""
    from services.events import engine as engine_mod

    note = _note_row(
        _confirmed_note(),
        entity_kind="person",
        entity_key="11111111-1111-1111-1111-111111111111",
    )
    db = _Db(
        fact_rows=[note],
        person_rows=[(uuid.UUID(note.entity_key), "Cleaner")],
    )
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))
    return engine_mod, db, note


def _daily_note_row(entity_kind, entity_key):
    return SimpleNamespace(
        id=uuid.uuid4(), status="established", suppresses_alerts=True,
        suppression_confirmed_at=datetime.now(timezone.utc),
        entity_kind=entity_kind, entity_key=entity_key,
        # An all-day, every-day window: matches whenever the test runs.
        schedule_days=[0, 1, 2, 3, 4, 5, 6],
        schedule_start_minute=0, schedule_end_minute=1440,
    )


def test_resolver_collects_subject_and_name_alias(monkeypatch):
    from services.events import engine as engine_mod

    pid = "22222222-2222-2222-2222-222222222222"
    db = _Db(
        fact_rows=[_daily_note_row("person", pid)],
        person_rows=[(uuid.UUID(pid), "Cleaner")],
    )
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))
    out = _run(engine_mod.RuleEngine._resolve_fact_suppressions(timezone.utc))
    assert out[("person", pid)] is not None
    assert out[("person", "Cleaner")] is not None  # association events key by name


def test_resolver_skips_household_notes(monkeypatch):
    """Household-wide notes name no subject, so they never join the
    suppression set — a note must match a subject to mute an alert.
    (Status/armed/confirmed filtering is SQL-side; the resolver trusts
    its indexed WHERE and re-checks schedule + entity in Python.)"""
    from services.events import engine as engine_mod

    db = _Db(fact_rows=[
        _daily_note_row("household", "household"),
        _daily_note_row("person", "33333333-3333-3333-3333-333333333333"),
    ])
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))
    out = _run(engine_mod.RuleEngine._resolve_fact_suppressions(timezone.utc))
    assert set(out) == {("person", "33333333-3333-3333-3333-333333333333")}


def test_suppression_hit_matches_subject_bearing_payloads_only(monkeypatch):
    from services.events import engine as engine_mod

    pid = "44444444-4444-4444-4444-444444444444"
    db = _Db(
        fact_rows=[_daily_note_row("person", pid)],
        person_rows=[(uuid.UUID(pid), "Cleaner")],
    )
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))
    sup = _run(engine_mod.RuleEngine._resolve_fact_suppressions(timezone.utc))
    hit = engine_mod.RuleEngine._suppression_hit

    # Association deviation: subject keyed by display name.
    assert hit(sup, {"type": "association_deviation"},
               {"subject_kind": "person", "subject_key": "Cleaner"}) is not None
    # Recognized face: keyed by person id.
    assert hit(sup, {"type": "face_recognized"},
               {"person_detections": {"faces": [{"person_id": pid}]}}) is not None
    # Vehicle and motion events name no suppressed subject.
    assert hit(sup, {"type": "vehicle_detected"},
               {"vehicle_detections": {"vehicles": [{"vehicle_id": str(uuid.uuid4())}]}}) is None
    assert hit(sup, {"type": "motion"}, {"motion_score": 0.9}) is None


def test_confirmed_note_silences_thursday_alerts_but_not_motion(
    monkeypatch, suppression_engine,
):
    engine_mod, db, note = suppression_engine
    from tests._engine_helpers import FakeRule, install_engine

    # Patterns as the engine sees them; the face rule targets anybody
    # recognized, the motion rule is a plain camera watch. Distinct action
    # markers let the assertions tell which rule fired.
    face_rule = FakeRule(name="person at door",
                         trigger_pattern={"type": "face_recognized"},
                         actions=[{"type": "broadcast", "marker": "face"}])
    motion_rule = FakeRule(name="motion watch", trigger_pattern={"type": "motion"},
                           actions=[{"type": "broadcast", "marker": "motion"}])
    engine, recorder = install_engine(monkeypatch, [face_rule, motion_rule])
    # Route the engine's resolver through our stubbed db.
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))

    # The all-day window stands in for "it is Thursday 10:00 right now":
    # schedule matching itself is covered precisely in test_fact_schedule.
    note.schedule_days = [0, 1, 2, 3, 4, 5, 6]
    note.schedule_start_minute, note.schedule_end_minute = 0, 1440

    payload = {
        "camera_id": str(uuid.uuid4()),
        "motion_score": 0.9,  # the same frame also trips plain motion
        "person_detections": {"count": 1, "faces": [
            {"person_id": "11111111-1111-1111-1111-111111111111",
             "person_name": "Cleaner"},
        ]},
    }
    _run(engine.evaluate(dict(payload)))

    markers = [call.args[0].get("marker") for call in recorder.call_args_list]
    assert "face" not in markers   # silenced by the note
    assert "motion" in markers     # not about the subject


def test_suppressed_hits_are_counted_on_the_note(monkeypatch, suppression_engine):
    engine_mod, db, note = suppression_engine
    from tests._engine_helpers import FakeRule, install_engine

    face_rule = FakeRule(name="person at door",
                         trigger_pattern={"type": "face_recognized"},
                         actions=[{"type": "broadcast", "marker": "face"}])
    engine, _recorder = install_engine(monkeypatch, [face_rule])
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))
    note.schedule_days = [0, 1, 2, 3, 4, 5, 6]
    note.schedule_start_minute, note.schedule_end_minute = 0, 1440

    payload = {
        "camera_id": str(uuid.uuid4()),
        "person_detections": {"count": 1, "faces": [
            {"person_id": "11111111-1111-1111-1111-111111111111"},
        ]},
    }
    _run(engine.evaluate(dict(payload)))
    assert db.updates == 1  # one throttled write, visible on the note

    # A second burst inside the throttle window writes nothing more.
    _run(engine.evaluate(dict(payload)))
    assert db.updates == 1


def test_out_of_window_schedule_suppresses_nothing(monkeypatch):
    from services.events import engine as engine_mod
    from tests._engine_helpers import FakeRule, install_engine

    note = SimpleNamespace(
        id=uuid.uuid4(), status="established", suppresses_alerts=True,
        suppression_confirmed_at=datetime.now(timezone.utc),
        entity_kind="person", entity_key="55555555-5555-5555-5555-555555555555",
        schedule_days=None,  # no schedule at all: never matches
        schedule_start_minute=None, schedule_end_minute=None,
    )
    db = _Db(fact_rows=[note])
    monkeypatch.setattr(engine_mod, "async_session", lambda: _SessionCtx(db))

    face_rule = FakeRule(name="person at door",
                         trigger_pattern={"type": "face_recognized"})
    engine, recorder = install_engine(monkeypatch, [face_rule])
    _run(engine.evaluate({
        "camera_id": str(uuid.uuid4()),
        "person_detections": {"count": 1, "faces": [
            {"person_id": "55555555-5555-5555-5555-555555555555"},
        ]},
    }))
    assert recorder.call_count == 1  # the note was inert


# ---- digest: the note explains the day ------------------------------------


def test_done_when_recap_prompt_carries_the_explanation():
    from services.perception.daily_digest import _build_prompt

    facts = {
        "notable_events": [
            {"ts": "2026-09-24T10:05:00+00:00", "when": "10:05 AM",
             "text": "Cleaner seen on Back Door"},
        ],
        "household_notes": [{
            "id": str(uuid.uuid4()),
            "text": "the cleaner comes Thursdays and has a key",
            "expected": True,
            "seen": "Cleaner",
            "schedule": "Thursdays 09:00-11:00",
            "source": "user",
        }],
    }
    prompt = _build_prompt(
        facts,
        datetime(2026, 9, 24, 4, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
    )
    assert "the cleaner comes Thursdays" in prompt
    assert "expected during this window" in prompt
    assert "as expected" in prompt  # the instruction that yields the citation


def test_schedule_note_counts_as_expected_even_without_sightings():
    """A note whose weekday matches the window rides along even when the
    cameras saw nothing: 'expected, and nothing showed' is a recap line."""
    from services.perception import daily_digest as dd

    note = SimpleNamespace(
        id=uuid.uuid4(), text="the cleaner comes Thursdays", source="user",
        status="established", pinned=False, evidence_count=1,
        entity_kind="person", entity_key="66666666-6666-6666-6666-666666666666",
        schedule_days=[3], schedule_start_minute=540, schedule_end_minute=660,
    )
    db = _Db(fact_rows=[note])
    window_end = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)  # Thursday, inside 9-11
    out = _run(dd._relevant_household_notes(
        db, window_end=window_end, tz=timezone.utc,
        named_persons=set(),  # nothing seen at all
        seen_camera_ids=set(), seen_vehicle_ids=set(), scoped=False,
    ))
    assert len(out) == 1 and out[0]["expected"] is True
