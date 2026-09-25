"""Memory: remember tool + household facts API (#286)."""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.agent.tools import setup_tools as st
from services.api.routes import household as hh


def _run(coro):
    return asyncio.run(coro)


# ── remember tool (confirm gate) ──

def test_remember_returns_confirm_proposal():
    out = _run(st.remember({"db": None, "user": None}, fact="the kids get home at 3:30pm"))
    assert out["ok"] is True
    ca = out["client_action"]
    assert ca["kind"] == "remember_fact"
    assert ca["method"] == "POST" and ca["path"] == "/api/household/facts"
    assert ca["body"] == {"text": "the kids get home at 3:30pm", "kind": "note"}
    assert "confirm" in out["message_for_user"].lower()


def test_remember_empty_is_rejected():
    out = _run(st.remember({"db": None, "user": None}, fact="   "))
    assert out["ok"] is False


def test_remember_is_registered():
    from services.agent.tools import TOOL_REGISTRY
    entry = next((t for t in TOOL_REGISTRY if t["name"] == "remember"), None)
    assert entry is not None
    # It carries no side-effect write; the confirm gate does the write.
    assert entry["side_effect"] == "read"


# ── facts API ──

class _FactsDB:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one
        self.added = []
        self.deleted = []

    def add(self, o):
        self.added.append(o)

    async def commit(self):
        pass

    async def refresh(self, o):
        pass

    async def get(self, model, ident):
        return self.one

    async def delete(self, o):
        self.deleted.append(o)

    async def execute(self, stmt):
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _fact(**kw):
    base = dict(
        id=uuid.uuid4(), text="dad's car is grey", subject_key="user:abc", kind="note",
        source="user", status="established", pinned=False, evidence_count=0,
        created_at=None, last_confirmed_at=None, archived_at=None,
        entity_kind="household", entity_key="household",
        schedule_days=None, schedule_start_minute=None, schedule_end_minute=None,
        schedule_tz=None, suppresses_alerts=False, suppression_confirmed_at=None,
        suppression_hit_count=0, last_suppressed_at=None, created_via="web",
        established_at=None, rejected_at=None, rejection_reason=None,
        evidence_refs=None, updated_at=None,
        created_by_user_id=None, updated_by_user_id=None,
        suppression_confirmed_by_user_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_create_fact_is_user_sourced_and_established():
    db = _FactsDB()
    out = _run(hh.create_fact(hh.FactCreate(text="remember this"), SimpleNamespace(id=uuid.uuid4()), db))
    assert out["source"] == "user"
    assert out["status"] == "established" and out["enabled"] is True
    assert db.added and db.added[0].source == "user"


def test_update_fact_edit_sets_text():
    f = _fact()
    db = _FactsDB(one=f)
    out = _run(hh.update_fact(f.id, hh.FactUpdate(text="dad's car is silver"), SimpleNamespace(id=uuid.uuid4()), db))
    assert f.text == "dad's car is silver"
    assert out["text"] == "dad's car is silver"


def test_disable_fact_archives_it():
    f = _fact(status="established")
    db = _FactsDB(one=f)
    out = _run(hh.update_fact(f.id, hh.FactUpdate(enabled=False), SimpleNamespace(id=uuid.uuid4()), db))
    assert f.status == "archived" and out["enabled"] is False


def test_enable_fact_restores_it():
    f = _fact(status="archived")
    db = _FactsDB(one=f)
    _run(hh.update_fact(f.id, hh.FactUpdate(enabled=True), SimpleNamespace(id=uuid.uuid4()), db))
    assert f.status == "established" and f.archived_at is None


def test_update_missing_fact_404():
    db = _FactsDB(one=None)
    with pytest.raises(Exception) as e:
        _run(hh.update_fact(uuid.uuid4(), hh.FactUpdate(text="x"), SimpleNamespace(id=uuid.uuid4()), db))
    assert "404" in str(e.value) or "not found" in str(e.value)


def test_delete_fact():
    f = _fact()
    db = _FactsDB(one=f)
    _run(hh.delete_fact(f.id, SimpleNamespace(id=uuid.uuid4()), db))
    assert db.deleted == [f]


def test_list_facts_shapes_source_and_enabled():
    db = _FactsDB(rows=[_fact(source="user", status="established"), _fact(source="agent", status="archived")])
    out = _run(hh.list_facts(include_archived=True, user=SimpleNamespace(id=uuid.uuid4(), role="admin"), db=db))
    assert {r["source"] for r in out} == {"user", "agent"}
    assert out[0]["enabled"] is True and out[1]["enabled"] is False


# ── #185: lifecycle, schedules, suppression, evidence ──────────────────

from sqlalchemy.dialects import postgresql  # noqa: E402
from shared.fact_schedule import schedule_summary  # noqa: E402


class _AwareDB(_FactsDB):
    """Knows about Person/Vehicle/Camera gets and captures list SQL."""

    def __init__(self, rows=None, one=None, entities=None, grants=()):
        super().__init__(rows=rows, one=one)
        self.entities = entities or {}
        self.grants = list(grants)
        self.last_sql = ""

    async def get(self, model, ident):
        if model.__name__ == "HouseholdFact":
            return self.one
        return self.entities.get((model.__name__, str(ident)))

    async def execute(self, stmt):
        self.last_sql = str(stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        ))
        sql = self.last_sql.lower()
        rows = list(self.rows)
        if "user_camera_access" in sql:
            rows = list(self.grants)
        elif "from persons" in sql:
            rows = [
                (uuid.UUID(k), v.display_name)
                for (m, k), v in self.entities.items()
                if m == "Person"
            ]
        elif "from vehicles" in sql:
            rows = [
                (uuid.UUID(k), v.display_name)
                for (m, k), v in self.entities.items()
                if m == "Vehicle"
            ]
        elif "from cameras" in sql:
            rows = [
                (uuid.UUID(k), v.name)
                for (m, k), v in self.entities.items()
                if m == "Camera"
            ]

        class _Scalars:
            def all(self):
                return rows

        class _Result:
            def all(self):
                return rows

            def scalars(self):
                return _Scalars()

        return _Result()


_ADMIN = dict(role="admin")


def _user(**kw):
    base = dict(id=uuid.uuid4(), role=None, camera_access_mode="all")
    base.update(kw)
    return SimpleNamespace(**base)


def test_create_note_attaches_to_a_person():
    pid = uuid.uuid4()
    db = _AwareDB(entities={("Person", str(pid)): SimpleNamespace(id=pid, display_name="Sara")})
    out = _run(hh.create_fact(
        hh.FactCreate(text="the cleaner comes Thursdays", entity_kind="person", entity_key=str(pid)),
        _user(**_ADMIN), db))
    assert out["entity_kind"] == "person" and out["entity_key"] == str(pid)
    assert out["entity_label"] == "Sara"
    assert out["suppresses_alerts"] is False  # never armed as a side effect


def test_create_note_household_by_default():
    db = _AwareDB()
    out = _run(hh.create_fact(hh.FactCreate(text="we holiday in August"), _user(**_ADMIN), db))
    assert out["entity_kind"] == "household" and out["entity_label"] == "Household"


def test_create_with_schedule_and_suppression_arms_in_one_confirm():
    db = _AwareDB()
    out = _run(hh.create_fact(
        hh.FactCreate(
            text="the cleaner comes Thursdays",
            schedule=hh.ScheduleBody(days=[3], start_minute=540, end_minute=660),
            suppress_alerts=True,
            via="agent_chat",
        ),
        _user(**_ADMIN), db))
    assert out["schedule"]["days"] == [3]
    assert out["schedule"]["summary"] == "Thursdays 09:00-11:00"
    assert out["suppression_armed"] is True and out["created_via"] == "agent_chat"


def test_create_suppression_requires_a_schedule():
    db = _AwareDB()
    with pytest.raises(Exception) as e:
        _run(hh.create_fact(
            hh.FactCreate(text="no schedule here", suppress_alerts=True),
            _user(**_ADMIN), db))
    assert "400" in str(e.value)


def test_create_camera_attach_out_of_scope_404():
    foreign = uuid.uuid4()
    db = _AwareDB(grants=[])  # restricted user with zero grants
    with pytest.raises(Exception) as e:
        _run(hh.create_fact(
            hh.FactCreate(text="gate cam note", entity_kind="camera", entity_key=str(foreign)),
            _user(role=None, camera_access_mode="selected"), db))
    assert "404" in str(e.value)


def test_decision_accept_promotes_candidate():
    f = _fact(status="candidate", source="agent")
    db = _AwareDB(one=f)
    out = _run(hh.decide_fact(f.id, hh.FactDecision(decision="accept"), _user(**_ADMIN), db))
    assert f.status == "established" and f.established_at is not None


def test_decision_accept_on_established_conflicts():
    f = _fact(status="established")
    db = _AwareDB(one=f)
    with pytest.raises(Exception) as e:
        _run(hh.decide_fact(f.id, hh.FactDecision(decision="accept"), _user(**_ADMIN), db))
    assert "409" in str(e.value)


def test_decision_reject_is_permanent_and_disarms():
    f = _fact(status="established", source="agent", suppresses_alerts=True,
              suppression_confirmed_at=datetime.now(timezone.utc))
    db = _AwareDB(one=f)
    out = _run(hh.decide_fact(
        f.id, hh.FactDecision(decision="reject", reason="that's not our cleaner"),
        _user(**_ADMIN), db))
    assert f.status == "rejected" and f.rejection_reason == "that's not our cleaner"
    assert out["suppresses_alerts"] is False and out["suppression_armed"] is False
    with pytest.raises(Exception) as e:
        _run(hh.decide_fact(f.id, hh.FactDecision(decision="accept"), _user(**_ADMIN), db))
    assert "409" in str(e.value)


def test_restore_brings_archived_back_and_reject_door_stays_shut():
    archived = _fact(status="archived", archived_at=datetime.now(timezone.utc))
    db = _AwareDB(one=archived)
    out = _run(hh.restore_fact(archived.id, _user(**_ADMIN), db))
    assert out["status"] == "established" and archived.archived_at is None

    rejected = _fact(status="rejected")
    db2 = _AwareDB(one=rejected)
    with pytest.raises(Exception) as e:
        _run(hh.restore_fact(rejected.id, _user(**_ADMIN), db2))
    assert "409" in str(e.value)


def test_suppression_arm_and_disarm():
    armed_on = datetime.now(timezone.utc)
    f = _fact(schedule_days=[3], schedule_start_minute=540, schedule_end_minute=660)
    db = _AwareDB(one=f)
    out = _run(hh.set_fact_suppression(f.id, hh.SuppressionUpdate(enabled=True), _user(**_ADMIN), db))
    assert out["suppresses_alerts"] is True and out["suppression_armed"] is True

    f2 = _fact(schedule_days=[3], schedule_start_minute=540, schedule_end_minute=660,
               suppresses_alerts=True, suppression_confirmed_at=armed_on)
    db2 = _AwareDB(one=f2)
    out2 = _run(hh.set_fact_suppression(f2.id, hh.SuppressionUpdate(enabled=False), _user(**_ADMIN), db2))
    assert out2["suppresses_alerts"] is False and out2["suppression_armed"] is False


def test_suppression_arm_requires_schedule_and_established():
    no_schedule = _fact()
    db = _AwareDB(one=no_schedule)
    with pytest.raises(Exception) as e:
        _run(hh.set_fact_suppression(no_schedule.id, hh.SuppressionUpdate(enabled=True), _user(**_ADMIN), db))
    assert "409" in str(e.value)

    candidate = _fact(status="candidate", schedule_days=[3],
                      schedule_start_minute=540, schedule_end_minute=660)
    db2 = _AwareDB(one=candidate)
    with pytest.raises(Exception) as e:
        _run(hh.set_fact_suppression(candidate.id, hh.SuppressionUpdate(enabled=True), _user(**_ADMIN), db2))
    assert "409" in str(e.value)


def test_editing_schedule_disarms_until_reconfirmed():
    f = _fact(schedule_days=[3], schedule_start_minute=540, schedule_end_minute=660,
              suppresses_alerts=True, suppression_confirmed_at=datetime.now(timezone.utc))
    db = _AwareDB(one=f)
    out = _run(hh.update_fact(
        f.id, hh.FactUpdate(schedule=hh.ScheduleBody(days=[4], start_minute=600, end_minute=720)),
        _user(**_ADMIN), db))
    assert out["schedule"]["days"] == [4]
    # The window changed under an armed note: suppression needs a fresh yes.
    assert out["suppresses_alerts"] is False and out["suppression_armed"] is False


def test_clearing_schedule_disarms_too():
    f = _fact(schedule_days=[3], schedule_start_minute=540, schedule_end_minute=660,
              suppresses_alerts=True, suppression_confirmed_at=datetime.now(timezone.utc))
    db = _AwareDB(one=f)
    out = _run(hh.update_fact(f.id, hh.FactUpdate(clear_schedule=True), _user(**_ADMIN), db))
    assert out["schedule"] is None and out["suppresses_alerts"] is False


def test_list_filters_scope_camera_attached_facts():
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    db = _AwareDB(grants=[(mine,)])
    _run(hh.list_facts(user=_user(role=None, camera_access_mode="selected"), db=db))
    # The scoping predicate must be in the SQL: camera-attached rows are
    # narrowed to the caller's grant set, everything else untouched.
    assert "entity_key" in db.last_sql
    assert str(mine) in db.last_sql and str(theirs) not in db.last_sql


def test_list_camera_filter_for_foreign_camera_404s():
    db = _AwareDB(grants=[])
    with pytest.raises(Exception) as e:
        _run(hh.list_facts(camera_id=str(uuid.uuid4()),
                           user=_user(role=None, camera_access_mode="selected"), db=db))
    assert "404" in str(e.value)


def test_list_unknown_status_400():
    db = _AwareDB()
    with pytest.raises(Exception) as e:
        _run(hh.list_facts(status="bogus", user=_user(**_ADMIN), db=db))
    assert "400" in str(e.value)


def test_evidence_view_resolves_associations():
    edge_id = uuid.uuid4()
    f = _fact(source="agent", evidence_refs=[{"kind": "association", "id": str(edge_id)}],
              evidence_count=12)

    class _EdgeRow:
        id = edge_id
        relation = "uses"
        subject_kind = "person"
        subject_key = "Ahmed"
        object_kind = "vehicle"
        object_key = "v-1"
        object_label = "Harrier"
        source = "learned"
        status = "established"
        distinct_days = 21
        evidence_count = 40
        hour_histogram = {"8": 38, "9": 2}
        first_seen_at = None
        last_seen_at = None

    db = _AwareDB(one=f, rows=[_EdgeRow()])
    out = _run(hh.fact_evidence(f.id, _user(**_ADMIN), db))
    assert out["evidence_count"] == 12
    ref = out["refs"][0]
    assert ref["relation"] == "uses" and ref["distinct_days"] == 21
    assert ref["usual_hours"] == [8, 9]


def test_evidence_view_marks_missing_refs():
    f = _fact(evidence_refs=[{"kind": "association", "id": str(uuid.uuid4())}])
    db = _AwareDB(one=f, rows=[])
    out = _run(hh.fact_evidence(f.id, _user(**_ADMIN), db))
    assert out["refs"][0]["missing"] is True


def test_user_note_evidence_is_the_note_itself():
    f = _fact(source="user", evidence_refs=None)
    db = _AwareDB(one=f)
    out = _run(hh.fact_evidence(f.id, _user(**_ADMIN), db))
    assert out["refs"] == []
