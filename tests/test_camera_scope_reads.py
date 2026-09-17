"""Camera-scope enforcement on the read surfaces closed by issue #201.

Endpoint-level negative tests: a selected-scope user (granted camera A
only) must not read another camera's journeys, VLM passes, single events,
event notes, or event counts. Each surface pairs a negative case (foreign
camera -> 404 / filtered out) with a positive control (own camera -> ok),
and the checks run against a stubbed AsyncSession, the DB-free convention
of this suite (see tests/test_verified_activation.py).

The stub dispatches ``db.execute`` on the compiled table name so the same
handler code paths that run in production run here unchanged:
``allowed_camera_ids`` really issues its ``user_camera_access`` query and
the handlers really apply the ACL.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services.api.routes import events as events_routes
from services.api.routes import journeys as journeys_routes
from services.api.routes import observations as observations_routes


def _run(coro):
    return asyncio.run(coro)


T0 = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

CAM_A = uuid.uuid4()   # the selected user's only granted camera
CAM_B = uuid.uuid4()   # a foreign camera the user must not reach


# ── users ────────────────────────────────────────────────────────────

def _selected_user(*grants):
    """A non-admin in 'selected' mode. ``grants`` are its allowed cameras."""
    return SimpleNamespace(
        id=uuid.uuid4(), role="user", camera_access_mode="selected", is_active=True,
        _grants=list(grants),
    )


# ── result / session stubs ───────────────────────────────────────────

class _Result:
    def __init__(self, *, scalar_rows=None, raw_rows=None, scalar_one=None):
        self._scalar_rows = list(scalar_rows or [])
        self._raw_rows = list(raw_rows or [])
        self._scalar_one = scalar_one

    def scalars(self):
        m = MagicMock()
        m.all.return_value = self._scalar_rows
        m.first.return_value = self._scalar_rows[0] if self._scalar_rows else None
        return m

    def all(self):
        return self._raw_rows

    def scalar_one(self):
        return self._scalar_one


class StubDB:
    """AsyncSession stand-in dispatching on the compiled table name.

    ``grants`` seeds the ``user_camera_access`` rows read by
    ``allowed_camera_ids``; ``get_map`` maps a model name to the object
    ``db.get(Model, id)`` returns; the row lists back the scalar reads.
    Every executed statement is captured in ``self.executed`` so a test can
    compile it and assert the ACL was pushed into the WHERE clause.
    """

    def __init__(self, *, grants=(), get_map=None, journeys=(), incidents=(),
                 vlm_passes=(), notes=(), feedback=(), count=0):
        self.grants = list(grants)
        self.get_map = get_map or {}
        self.journeys = list(journeys)
        self.incidents = list(incidents)
        self.vlm_passes = list(vlm_passes)
        self.notes = list(notes)
        self.feedback = list(feedback)
        self.count = count
        self.executed: list = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        sql = str(stmt).lower()
        if "user_camera_access" in sql:
            return _Result(raw_rows=[(g,) for g in self.grants])
        if "count(" in sql:
            return _Result(scalar_one=self.count)
        if "event_notes" in sql:
            return _Result(scalar_rows=self.notes)
        if "event_feedback" in sql:
            return _Result(scalar_rows=self.feedback)
        if "observation_vlm_passes" in sql:
            return _Result(scalar_rows=self.vlm_passes)
        # Order matters: the journeys select carries an ``incidents_count``
        # column, so match the FROM table (``from journeys``) before the
        # broader ``incidents`` substring.
        if "from journeys" in sql:
            return _Result(scalar_rows=self.journeys)
        if "incidents" in sql:
            return _Result(scalar_rows=self.incidents)
        return _Result()

    async def get(self, model, _ident):
        return self.get_map.get(model.__name__)


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ── factories ────────────────────────────────────────────────────────

def _journey(*cam_ids, **kw):
    base = dict(
        id=uuid.uuid4(), subject_kind="person", subject_key="Ann",
        started_at=T0, last_seen_at=T0, ended_at=None, finalized=True,
        segments=[{"camera_id": str(c)} for c in cam_ids],
        transitions=[], cameras_seen_count=len(cam_ids), incidents_count=1,
        summary_text=None, summary_provider_name=None, created_at=T0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _incident(cam_id):
    return SimpleNamespace(
        id=uuid.uuid4(), camera_id=cam_id, started_at=T0, last_seen_at=T0,
        occurrence_count=1, finalized=True, summary_text=None,
        thumbnails=None, peak_observation_id=None,
    )


def _observation(cam_id):
    return SimpleNamespace(id=uuid.uuid4(), camera_id=cam_id)


def _event(cam_id):
    return SimpleNamespace(id=uuid.uuid4(), camera_id=cam_id)


# ── journeys ─────────────────────────────────────────────────────────

def test_list_journeys_hides_foreign_camera_journeys():
    mine = _journey(CAM_A)
    foreign = _journey(CAM_B)
    db = StubDB(grants=[CAM_A], journeys=[mine, foreign])
    out = _run(journeys_routes.list_journeys(
        subject_kind=None, subject_key=None, finalized=None, from_=None, to=None,
        limit=50, offset=0, user=_selected_user(CAM_A), db=db,
    ))
    ids = {row["id"] for row in out}
    assert ids == {str(mine.id)}
    assert str(foreign.id) not in ids


def test_get_journey_on_foreign_camera_is_404():
    foreign = _journey(CAM_B)
    db = StubDB(grants=[CAM_A], get_map={"Journey": foreign})
    with pytest.raises(HTTPException) as ei:
        _run(journeys_routes.get_journey(journey_id=foreign.id, user=_selected_user(CAM_A), db=db))
    assert ei.value.status_code == 404


def test_get_journey_own_camera_scopes_incident_hydrate():
    mine = _journey(CAM_A)
    db = StubDB(grants=[CAM_A], get_map={"Journey": mine}, incidents=[_incident(CAM_A)])
    payload = _run(journeys_routes.get_journey(journey_id=mine.id, user=_selected_user(CAM_A), db=db))
    assert payload["id"] == str(mine.id)
    assert len(payload["incidents"]) == 1
    # The incident hydrate query must carry the ACL: CAM_A in, CAM_B never.
    inc_stmts = [s for s in db.executed if "incidents" in str(s).lower()]
    assert inc_stmts, "incident hydrate query was not issued"
    compiled = _compiled(inc_stmts[-1]).replace("-", "")
    assert CAM_A.hex in compiled
    assert CAM_B.hex not in compiled


def test_reinterpret_journey_on_foreign_camera_is_404():
    foreign = _journey(CAM_B)
    db = StubDB(grants=[CAM_A], get_map={"Journey": foreign})
    with pytest.raises(HTTPException) as ei:
        _run(journeys_routes.reinterpret_journey(journey_id=foreign.id, body=None, user=_selected_user(CAM_A), db=db))
    assert ei.value.status_code == 404


# ── observation VLM passes ───────────────────────────────────────────

def test_vlm_passes_on_foreign_camera_is_404():
    obs = _observation(CAM_B)
    db = StubDB(grants=[CAM_A], get_map={"Observation": obs})
    with pytest.raises(HTTPException) as ei:
        _run(observations_routes.get_vlm_passes(observation_id=obs.id, current_user=_selected_user(CAM_A), db=db))
    assert ei.value.status_code == 404


def test_vlm_passes_own_camera_returns_history():
    obs = _observation(CAM_A)
    db = StubDB(grants=[CAM_A], get_map={"Observation": obs}, vlm_passes=[])
    out = _run(observations_routes.get_vlm_passes(observation_id=obs.id, current_user=_selected_user(CAM_A), db=db))
    assert out == []


# ── single event + notes ─────────────────────────────────────────────

def test_get_event_on_foreign_camera_is_404():
    ev = _event(CAM_B)
    db = StubDB(grants=[CAM_A], get_map={"Event": ev})
    with pytest.raises(HTTPException) as ei:
        _run(events_routes.get_event(event_id=ev.id, current_user=_selected_user(CAM_A), db=db))
    assert ei.value.status_code == 404


def test_list_event_notes_on_foreign_camera_is_404():
    ev = _event(CAM_B)
    db = StubDB(grants=[CAM_A], get_map={"Event": ev})
    with pytest.raises(HTTPException) as ei:
        _run(events_routes.list_event_notes(event_id=ev.id, current_user=_selected_user(CAM_A), db=db))
    assert ei.value.status_code == 404


def test_list_event_notes_own_camera_ok():
    ev = _event(CAM_A)
    db = StubDB(grants=[CAM_A], get_map={"Event": ev}, notes=[])
    out = _run(events_routes.list_event_notes(event_id=ev.id, current_user=_selected_user(CAM_A), db=db))
    assert out == []


# ── event count ──────────────────────────────────────────────────────

def test_events_count_query_is_camera_scoped():
    db = StubDB(grants=[CAM_A], count=0)
    _run(events_routes.events_count(
        acked=None, severity=None, rule_id=None, from_=None,
        current_user=_selected_user(CAM_A), db=db,
    ))
    count_stmts = [s for s in db.executed if "count(" in str(s).lower()]
    assert count_stmts, "count query was not issued"
    compiled = _compiled(count_stmts[-1]).replace("-", "")
    # The badge count is restricted to the granted camera; a foreign one
    # never appears in the WHERE clause.
    assert CAM_A.hex in compiled
    assert CAM_B.hex not in compiled


def test_events_count_empty_grant_scopes_to_nothing():
    # A selected user with no grants must count against an empty allowlist,
    # never against every camera.
    db = StubDB(grants=[], count=0)
    user = SimpleNamespace(id=uuid.uuid4(), role="user", camera_access_mode="selected")
    _run(events_routes.events_count(
        acked=None, severity=None, rule_id=None, from_=None, current_user=user, db=db,
    ))
    count_stmts = [s for s in db.executed if "count(" in str(s).lower()]
    compiled = _compiled(count_stmts[-1]).lower()
    # apply_camera_filter on an empty set forces `IN (NULL)` -> no rows.
    assert "camera_id in" in compiled
