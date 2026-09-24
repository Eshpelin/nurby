"""Incident resolution + ownership workflow (#197).

Route handlers are invoked directly with stubbed dependencies (matching
test_no_vlm_graceful's style): resolve / dismiss / reopen / assign set the
right state and record who + when, permission is enforced on the incident's
camera, and assignment validates the assignee.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.api.routes import incidents as inc


def _run(coro):
    return asyncio.run(coro)


def _incident(camera_id=None):
    now = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(), camera_id=camera_id or uuid.uuid4(),
        signature_kind="person", signature_key="Sara",
        started_at=now, last_seen_at=now, ended_at=None, finalized=True,
        occurrence_count=3, peak_observation_id=None, observation_ids=[],
        thumbnails=None, summary_text=None, summary_provider_name=None,
        conversation_id=None, journey_id=None, created_at=now,
        status="open", resolution_reason=None, resolved_at=None,
        resolved_by_user_id=None, assigned_to_user_id=None,
    )


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, incident, users=None):
        self.incident = incident
        self.users = users or {}
        self.committed = False
        self.logged: list = []  # IncidentEvent rows appended via add()

    def add(self, obj):
        self.logged.append(obj)

    async def get(self, model, ident):
        if model.__name__ == "Incident":
            return self.incident if ident == self.incident.id else None
        if model.__name__ == "User":
            return self.users.get(ident)
        return None

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        return None

    async def execute(self, stmt):
        t = str(stmt).lower()
        if "from incident_events" in t:
            return _Res(list(self.logged))
        # User name lookups (both ownership pointers and audit-log actors).
        return _Res([(uid, u.display_name, u.email) for uid, u in self.users.items()])


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), role="admin", is_active=True,
                           display_name="Ops", email="ops@x.com")


def test_resolve_sets_status_owner_and_reason():
    user = _admin()
    row = _incident()
    db = _DB(row, users={user.id: user})
    out = _run(inc.resolve_incident(row.id, inc.ResolveRequest(reason="false alarm"), user, db))
    assert row.status == "resolved"
    assert row.resolved_by_user_id == user.id
    assert row.resolved_at is not None
    assert row.resolution_reason == "false alarm"
    assert out["status"] == "resolved"
    assert out["ownership"]["resolved_by"] == "Ops"  # display name, not raw id
    assert db.committed


def test_dismiss_sets_dismissed():
    user = _admin()
    row = _incident()
    out = _run(inc.dismiss_incident(row.id, inc.ResolveRequest(reason="not relevant"),
                                    user, _DB(row, {user.id: user})))
    assert out["status"] == "dismissed"
    assert row.resolved_by_user_id == user.id


def test_reopen_clears_resolution():
    user = _admin()
    row = _incident()
    row.status = "resolved"
    row.resolved_by_user_id = user.id
    row.resolved_at = datetime.now(timezone.utc)
    row.resolution_reason = "x"
    out = _run(inc.reopen_incident(row.id, user, _DB(row, {user.id: user})))
    assert out["status"] == "open"
    assert row.resolved_at is None and row.resolved_by_user_id is None
    assert row.resolution_reason is None


def test_assign_and_unassign():
    user = _admin()
    assignee = SimpleNamespace(id=uuid.uuid4(), display_name="Alice", email="a@x.com")
    row = _incident()
    db = _DB(row, users={user.id: user, assignee.id: assignee})
    out = _run(inc.assign_incident(row.id, inc.AssignRequest(user_id=assignee.id), user, db))
    assert row.assigned_to_user_id == assignee.id
    assert out["ownership"]["assigned_to"] == "Alice"
    # Unassign.
    _run(inc.assign_incident(row.id, inc.AssignRequest(user_id=None), user, db))
    assert row.assigned_to_user_id is None


def test_assign_unknown_user_404():
    user = _admin()
    row = _incident()
    db = _DB(row, users={user.id: user})
    with pytest.raises(Exception) as exc:
        _run(inc.assign_incident(row.id, inc.AssignRequest(user_id=uuid.uuid4()), user, db))
    assert "404" in str(exc.value) or "not found" in str(exc.value)


def test_resolve_foreign_incident_is_404():
    # A restricted (no-access) user cannot resolve an incident on a camera
    # they cannot see: permission is enforced before any mutation.
    restricted = SimpleNamespace(id=uuid.uuid4(), role="viewer", is_active=True,
                                 camera_access_mode="none")
    row = _incident()
    db = _DB(row, users={})
    with pytest.raises(Exception) as exc:
        _run(inc.resolve_incident(row.id, inc.ResolveRequest(reason="x"), restricted, db))
    assert "404" in str(exc.value) or "not found" in str(exc.value)
    assert row.status == "open"  # untouched
    assert db.committed is False


# ── audit log history (#197 Phase 2) ──

def test_audit_log_records_each_transition():
    user = _admin()
    row = _incident()
    db = _DB(row, users={user.id: user})
    _run(inc.resolve_incident(row.id, inc.ResolveRequest(reason="handled"), user, db))
    _run(inc.reopen_incident(row.id, user, db))
    out = _run(inc.dismiss_incident(row.id, inc.ResolveRequest(reason="nope"), user, db))
    actions = [e.action for e in db.logged]
    assert actions == ["resolved", "reopened", "dismissed"]
    # History survives reopen (unlike the single resolved_by pointer).
    hist = out["ownership"]["history"]
    assert [h["action"] for h in hist] == ["resolved", "reopened", "dismissed"]
    assert hist[0]["actor"] == "Ops" and hist[0]["reason"] == "handled"


def test_assign_logs_actor_and_detail():
    user = _admin()
    assignee = SimpleNamespace(id=uuid.uuid4(), display_name="Alice", email="a@x.com")
    row = _incident()
    db = _DB(row, users={user.id: user, assignee.id: assignee})
    _run(inc.assign_incident(row.id, inc.AssignRequest(user_id=assignee.id), user, db))
    _run(inc.assign_incident(row.id, inc.AssignRequest(user_id=None), user, db))
    assert [e.action for e in db.logged] == ["assigned", "unassigned"]
    assert db.logged[0].detail == "Alice"


# ── detail enrichment helpers (#197 Phase 1) ──

class _DispatchDB:
    """Dispatches execute() by table name for the enrichment helpers."""

    def __init__(self, *, events=None, rules=None, notes=None, incidents=None, recording=None):
        self._events = events or []
        self._rules = rules or []
        self._notes = notes or []
        self._incidents = incidents or []
        self._recording = recording
        self._got = None

    async def get(self, model, ident):
        if model.__name__ == "Observation":
            return self._got
        return None

    async def execute(self, stmt):
        t = str(stmt).lower()
        if "from events" in t:
            return _Res(self._events)
        if "from rules" in t:
            return _Res(self._rules)
        if "from event_notes" in t:
            return _Res(self._notes)
        if "from incidents" in t:
            return _Res(self._incidents)
        if "from recordings" in t:
            return _Res([self._recording] if self._recording else [])
        return _Res([])


def test_incident_alerts_maps_trigger_and_action():
    rid = uuid.uuid4()
    ev = SimpleNamespace(
        id=uuid.uuid4(), fired_at=datetime.now(timezone.utc), severity="alert",
        rule_id=rid, action_type="telegram", action_status="sent", action_error=None,
        acked_at=None,
    )
    db = _DispatchDB(events=[ev], rules=[(rid, "Front door while away")], notes=[])
    out = _run(inc._incident_alerts(db, [uuid.uuid4()]))
    assert out[0]["trigger_reason"] == "Front door while away"
    assert out[0]["action_status"] == "sent"
    assert out[0]["seen"] is False


def test_incident_alerts_empty_without_obs():
    db = _DispatchDB()
    assert _run(inc._incident_alerts(db, [])) == []


def test_related_sightings_scoped_to_journey():
    from shared.camera_access import ALL
    jid = uuid.uuid4()
    inc_row = _incident()
    inc_row.journey_id = jid
    sib = _incident()
    sib.summary_text = "seen at the gate"
    db = _DispatchDB(incidents=[sib])
    out = _run(inc._related_sightings(db, inc_row, ALL))
    assert out and out[0]["summary_text"] == "seen at the gate"


def test_related_sightings_none_without_journey():
    from shared.camera_access import ALL
    db = _DispatchDB()
    assert _run(inc._related_sightings(db, _incident(), ALL)) == []


def test_exact_clip_finds_covering_recording():
    row = _incident()
    rec = SimpleNamespace(
        id=uuid.uuid4(), started_at=row.started_at, ended_at=None, thumbnail_path="/t.jpg",
    )
    db = _DispatchDB(recording=rec)
    out = _run(inc._exact_clip(db, row))
    assert out["recording_id"] == str(rec.id)
    assert out["anchor_at"] == row.started_at.isoformat()


def test_exact_clip_none_when_no_recording():
    db = _DispatchDB(recording=None)
    assert _run(inc._exact_clip(db, _incident())) is None
