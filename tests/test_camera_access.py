"""Per-user camera ACL foundation (issue #40).

Covers the central ``shared.camera_access`` helper (admin vs restricted
vs no-grants policy) and ``apply_camera_filter``'s effect on the actual
list-endpoint query builders. The suite has no live Postgres, so the
helper is exercised against a tiny ``FakeDB`` stub (mirrors
``tests/test_agent_tools.py``) and the SQL is validated by compiling it
for the Postgres dialect (mirrors ``tests/test_recordings_filters.py``).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from services.api.routes.events import _filtered_events_query
from services.api.routes.recordings import _filtered_recordings_query
from shared.camera_access import ALL, allowed_camera_ids, apply_camera_filter
from shared.models import Camera, Observation

# ── stubs (mirror tests/test_agent_tools.py) ────────────────────────


def _user(role: str = "admin") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)


class FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeDB:
    """Stub AsyncSession whose ``execute`` returns canned rows keyed by
    the statement string. Only ``execute`` is needed here."""

    def __init__(self, responder):
        self._responder = responder

    async def execute(self, stmt):
        return FakeResult(self._responder(str(stmt)))


def _sql(query) -> str:
    return str(
        query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


# ── allowed_camera_ids policy ───────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_returns_all_sentinel_without_querying():
    def responder(stmt: str):
        raise AssertionError("admin must not hit user_camera_access")

    db = FakeDB(responder)
    result = await allowed_camera_ids(_user("admin"), db)
    assert result is ALL


@pytest.mark.asyncio
async def test_restricted_user_with_grants_returns_that_set():
    granted = {uuid.uuid4(), uuid.uuid4()}

    def responder(stmt: str):
        assert "user_camera_access" in stmt.lower()
        return [(cid,) for cid in granted]

    db = FakeDB(responder)
    result = await allowed_camera_ids(_user("viewer"), db)
    assert result == granted


@pytest.mark.asyncio
async def test_restricted_user_with_no_grants_falls_through_to_all():
    # The single-owner no-op: a restricted account with zero grants still
    # sees everything, so existing deploys are unchanged by this change.
    def responder(stmt: str):
        return []

    db = FakeDB(responder)
    result = await allowed_camera_ids(_user("viewer"), db)
    assert result is ALL


@pytest.mark.asyncio
async def test_guardian_role_is_treated_as_restricted():
    granted = {uuid.uuid4()}

    def responder(stmt: str):
        return [(cid,) for cid in granted]

    db = FakeDB(responder)
    result = await allowed_camera_ids(_user("guardian"), db)
    assert result == granted


# ── apply_camera_filter ─────────────────────────────────────────────


def test_apply_filter_all_is_noop():
    base = select(Camera)
    out = apply_camera_filter(base, ALL, Camera.id)
    assert out is base
    assert "where" not in _sql(out)


def test_apply_filter_set_adds_in_clause():
    ids = {uuid.uuid4(), uuid.uuid4()}
    out = apply_camera_filter(select(Camera), ids, Camera.id)
    sql = _sql(out)
    assert "where" in sql
    assert "in (" in sql
    for cid in ids:
        assert str(cid) in sql


def test_apply_filter_empty_set_forces_empty_result():
    # An explicit-but-empty allowlist must fail closed (return nothing),
    # never silently widen to all cameras.
    out = apply_camera_filter(select(Observation), set(), Observation.camera_id)
    sql = _sql(out)
    assert "where" in sql
    # IN () compiles to a guaranteed-false predicate on Postgres.
    assert "in (null)" in sql or "1 != 1" in sql or "in ()" in sql


# ── list-endpoint query builders honor the ACL ──────────────────────


def test_recordings_builder_default_all_is_unscoped():
    # Existing callers/tests pass no ``allowed`` and must stay unscoped.
    sql = _sql(_filtered_recordings_query(None, None, None, None))
    assert "from recordings" in sql
    assert "where" not in sql


def test_recordings_builder_restricted_adds_camera_in_clause():
    ids = {uuid.uuid4(), uuid.uuid4()}
    sql = _sql(_filtered_recordings_query(None, None, None, None, ids))
    assert "camera_id in (" in sql
    for cid in ids:
        assert str(cid) in sql


def test_recordings_builder_all_sentinel_is_unscoped():
    sql = _sql(_filtered_recordings_query(None, None, None, None, ALL))
    assert "where" not in sql


@pytest.mark.asyncio
async def test_events_builder_default_all_is_unscoped():
    db = FakeDB(lambda stmt: [])
    query = await _filtered_events_query(db)
    sql = _sql(query)
    assert "from events" in sql
    assert "camera_id in (" not in sql


@pytest.mark.asyncio
async def test_events_builder_restricted_adds_camera_in_clause():
    ids = {uuid.uuid4(), uuid.uuid4()}
    db = FakeDB(lambda stmt: [])
    query = await _filtered_events_query(db, allowed=ids)
    sql = _sql(query)
    assert "camera_id in (" in sql
    for cid in ids:
        assert str(cid) in sql


# ── owner vs restricted, end to end on the builder ──────────────────


def test_owner_sees_all_rows_restricted_sees_subset():
    """The core invariant: an owner (ALL) gets no camera predicate, a
    restricted user (set) gets one scoping to exactly their cameras."""
    owner_sql = _sql(_filtered_recordings_query(None, None, None, None, ALL))
    assert "camera_id in (" not in owner_sql

    one = uuid.uuid4()
    restricted_sql = _sql(_filtered_recordings_query(None, None, None, None, {one}))
    assert "camera_id in (" in restricted_sql
    assert str(one) in restricted_sql


# ── WS fan-out per-recipient scoping (issue #40, services/api/ws.py) ──
#
# The dashboard socket caches each connection's allowed-camera set at
# connect time; ``_deliver_local`` drops camera-tagged messages a given
# recipient may not see. These exercise the pure decision function and the
# real delivery loop against a fake socket registry, so a restricted socket
# never receives another camera's stream while ALL / untagged still flow.

from services.api import ws as ws_mod  # noqa: E402
from services.api.ws import _allowed_to_receive, _deliver_local  # noqa: E402


def test_ws_all_recipient_receives_every_camera():
    msg = {"type": "event", "camera_id": str(uuid.uuid4())}
    assert _allowed_to_receive(ALL, msg) is True


def test_ws_restricted_recipient_drops_foreign_camera():
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    assert _allowed_to_receive({mine}, {"type": "event", "camera_id": str(mine)}) is True
    assert _allowed_to_receive({mine}, {"type": "event", "camera_id": str(theirs)}) is False


def test_ws_untagged_system_message_reaches_everyone():
    # A message with no camera_id (system notice) is delivered regardless of
    # how narrow the recipient's allowlist is, even an empty one.
    assert _allowed_to_receive(set(), {"type": "system", "message": "hi"}) is True
    assert _allowed_to_receive({uuid.uuid4()}, {"type": "ack"}) is True


def test_ws_empty_allowlist_fails_closed_on_tagged_message():
    assert _allowed_to_receive(set(), {"type": "event", "camera_id": str(uuid.uuid4())}) is False


def test_ws_camera_id_as_uuid_or_string_both_match():
    cid = uuid.uuid4()
    assert _allowed_to_receive({cid}, {"type": "event", "camera_id": cid}) is True
    assert _allowed_to_receive({cid}, {"type": "event", "camera_id": str(cid)}) is True


class _FakeSocket:
    """Records the payloads ``_deliver_local`` would send to one client."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_deliver_local_routes_per_recipient_allowlist(monkeypatch):
    cam_a = uuid.uuid4()
    cam_b = uuid.uuid4()
    owner = _FakeSocket()           # ALL: sees everything
    only_a = _FakeSocket()          # restricted to cam_a
    none_sock = _FakeSocket()       # empty allowlist: only untagged

    registry = {owner: ALL, only_a: {cam_a}, none_sock: set()}
    monkeypatch.setattr(ws_mod, "_connections", registry)

    # A cam_b-tagged message: only the owner gets it.
    await _deliver_local(json.dumps({"type": "event", "camera_id": str(cam_b)}))
    assert len(owner.sent) == 1
    assert only_a.sent == []
    assert none_sock.sent == []

    # A cam_a-tagged message: owner + the cam_a-scoped socket.
    await _deliver_local(json.dumps({"type": "event", "camera_id": str(cam_a)}))
    assert len(owner.sent) == 2
    assert len(only_a.sent) == 1
    assert none_sock.sent == []

    # An untagged system message reaches every socket, even the empty one.
    await _deliver_local(json.dumps({"type": "system", "message": "maintenance"}))
    assert len(owner.sent) == 3
    assert len(only_a.sent) == 2
    assert len(none_sock.sent) == 1


# ── media-serving byte endpoints scope to 404, not 403 (issue #40) ────
#
# A restricted caller asking for a recording/observation/camera on a
# camera outside their allowlist gets 404 (so ids cannot be probed), while
# an owned camera passes through. These drive the real handler-internal
# scoping seams directly, avoiding JWT/HTTP plumbing.

import services.api.routes.cameras as cameras_mod  # noqa: E402
from services.api.routes.observations import (  # noqa: E402
    _camera_in_scope as _obs_in_scope,
)
from services.api.routes.recordings import (  # noqa: E402
    _camera_in_scope as _rec_in_scope,
)
from services.api.routes.recordings import _get_recording_or_404  # noqa: E402


class _GetDB:
    """Stub session whose ``get(model, id)`` returns canned rows."""

    def __init__(self, rows: dict):
        self._rows = rows

    async def get(self, model, ident):
        return self._rows.get((model.__name__, ident))


def test_camera_in_scope_all_and_set():
    cid = uuid.uuid4()
    other = uuid.uuid4()
    # ALL sees any camera (and a null camera_id).
    assert _rec_in_scope(ALL, cid) is True
    assert _rec_in_scope(ALL, None) is True
    # A concrete allowlist scopes precisely and excludes null-camera rows.
    assert _rec_in_scope({cid}, cid) is True
    assert _rec_in_scope({cid}, other) is False
    assert _rec_in_scope({cid}, None) is False
    # Observations share the same contract.
    assert _obs_in_scope({cid}, cid) is True
    assert _obs_in_scope({cid}, other) is False


@pytest.mark.asyncio
async def test_get_recording_404_for_cross_user_camera():
    owned = uuid.uuid4()
    foreign_cam = uuid.uuid4()
    rec_id = uuid.uuid4()
    db = _GetDB({("Recording", rec_id): SimpleNamespace(id=rec_id, camera_id=foreign_cam)})

    # Restricted to a camera that is NOT the recording's camera -> 404.
    with pytest.raises(HTTPException) as exc:
        await _get_recording_or_404(rec_id, db, {owned})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_recording_200_for_owned_camera():
    owned = uuid.uuid4()
    rec_id = uuid.uuid4()
    row = SimpleNamespace(id=rec_id, camera_id=owned)
    db = _GetDB({("Recording", rec_id): row})

    got = await _get_recording_or_404(rec_id, db, {owned})
    assert got is row

    # ALL (admin / zero-grant) also passes through.
    got2 = await _get_recording_or_404(rec_id, db, ALL)
    assert got2 is row


@pytest.mark.asyncio
async def test_camera_require_scope_404_and_passthrough():
    owned = uuid.uuid4()
    foreign = uuid.uuid4()

    # Restricted caller hitting a camera outside the allowlist: resolve the
    # grant set via the fake execute, then expect a 404.
    def restricted_responder(stmt: str):
        return [(owned,)]

    db = FakeDB(restricted_responder)
    with pytest.raises(HTTPException) as exc:
        await cameras_mod._require_camera_in_scope(foreign, _user("viewer"), db)
    assert exc.value.status_code == 404

    # The owned camera passes (no raise).
    await cameras_mod._require_camera_in_scope(owned, _user("viewer"), db)

    # Admin bypasses entirely (ALL), even on a camera with no grant row.
    admin_db = FakeDB(lambda stmt: (_ for _ in ()).throw(AssertionError("admin must not query")))
    await cameras_mod._require_camera_in_scope(foreign, _user("admin"), admin_db)


# Sanity: timestamps used above are tz-aware (parity with sibling suites).
def test_tz_aware_marker():
    assert datetime.now(timezone.utc).tzinfo is not None
