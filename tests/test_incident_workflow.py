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


class _DB:
    def __init__(self, incident, users=None):
        self.incident = incident
        self.users = users or {}
        self.committed = False

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
        # Only used by _ownership's User name lookup.
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
