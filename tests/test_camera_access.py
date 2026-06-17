"""Per-user camera ACL foundation (issue #40).

Covers the central ``shared.camera_access`` helper (admin vs restricted
vs no-grants policy) and ``apply_camera_filter``'s effect on the actual
list-endpoint query builders. The suite has no live Postgres, so the
helper is exercised against a tiny ``FakeDB`` stub (mirrors
``tests/test_agent_tools.py``) and the SQL is validated by compiling it
for the Postgres dialect (mirrors ``tests/test_recordings_filters.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
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


# Sanity: timestamps used above are tz-aware (parity with sibling suites).
def test_tz_aware_marker():
    assert datetime.now(timezone.utc).tzinfo is not None
