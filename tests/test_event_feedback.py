"""Structured alert feedback (#195): useful / correct-but-not-useful /
incorrect, with an optional reason for incorrect alerts.

The suite has no live Postgres, so the endpoints are called directly
against a scripted fake session (mirrors ``tests/test_camera_access.py``)
and the real ``shared.camera_access`` policy decides visibility. The
rating/reason validation lives in the Pydantic schema and is exercised
through the HTTP layer at the end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from services.api.routes import events as events_routes
from shared.models import EventFeedback
from shared.schemas import EventFeedbackCreate

# ── stubs ───────────────────────────────────────────────────────────


def _user(role: str = "admin") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), role=role, is_active=True, camera_access_mode="selected",
        display_name=None, email="viewer@example.com",
    )


def _event(camera_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), camera_id=camera_id,
        fired_at=datetime.now(timezone.utc), payload={}, notes=[],
    )


def _fb(event_id: uuid.UUID, user_id: uuid.UUID, rating: str = "useful",
        reason: str | None = None) -> EventFeedback:
    now = datetime.now(timezone.utc)
    return EventFeedback(
        id=uuid.uuid4(), event_id=event_id, user_id=user_id,
        rating=rating, reason=reason, created_at=now, updated_at=now,
    )


class FakeResult:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None):
        self._rows = rows if rows is not None else []
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar


class FeedbackDB:
    """Scripted fake AsyncSession.

    ``execute`` answers by position from ``responses`` (the endpoint call
    order is fixed and short), and ``get`` serves canned model rows. The
    fake records adds/deletes/commits so tests can assert on outcomes.
    """

    def __init__(self, responses: list[Any] | None = None,
                 objects: dict | None = None):
        self._responses = list(responses or [])
        self._objects = dict(objects or {})
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commits = 0
        self.rolled_back = 0

    async def get(self, model, key):
        return self._objects.get((model.__name__, key))

    async def execute(self, stmt):
        return self._responses.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rolled_back += 1

    async def refresh(self, obj):
        return obj


def _none_result():
    return FakeResult(scalar=None)


def _grant_result(grants: set[uuid.UUID]):
    return FakeResult(rows=[(cid,) for cid in grants])


# ── visibility ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_event_is_404_before_any_scope_check():
    db = FeedbackDB(objects={})
    with pytest.raises(HTTPException) as exc:
        await events_routes.set_event_feedback(
            uuid.uuid4(), EventFeedbackCreate(rating="useful"), _user(), db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_foreign_camera_event_is_a_404_not_a_403():
    """A restricted user must not learn that a foreign event exists."""
    cam = uuid.uuid4()
    ev = _event(cam)
    db = FeedbackDB(responses=[_grant_result(set())], objects={("Event", ev.id): ev})
    with pytest.raises(HTTPException) as exc:
        await events_routes.set_event_feedback(
            ev.id, EventFeedbackCreate(rating="useful"), _user("viewer"), db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_selected_user_without_camera_access_cannot_rate():
    cam = uuid.uuid4()
    other = uuid.uuid4()
    ev = _event(cam)
    db = FeedbackDB(
        responses=[_grant_result({other})],  # grant on a different camera
        objects={("Event", ev.id): ev},
    )
    with pytest.raises(HTTPException) as exc:
        await events_routes.set_event_feedback(
            ev.id, EventFeedbackCreate(rating="useful"), _user("viewer"), db,
        )
    assert exc.value.status_code == 404
    assert db.commits == 0 and not db.added


@pytest.mark.asyncio
async def test_granted_viewer_can_rate():
    cam = uuid.uuid4()
    ev = _event(cam)
    db = FeedbackDB(
        responses=[_grant_result({cam}), _none_result()],
        objects={("Event", ev.id): ev},
    )
    res = await events_routes.set_event_feedback(
        ev.id, EventFeedbackCreate(rating="useful"), _user("viewer"), db,
    )
    assert res["rating"] == "useful"
    assert db.commits == 1 and len(db.added) == 1


@pytest.mark.asyncio
async def test_admin_can_rate_any_event():
    ev = _event(uuid.uuid4())
    db = FeedbackDB(responses=[_none_result()], objects={("Event", ev.id): ev})
    res = await events_routes.set_event_feedback(
        ev.id, EventFeedbackCreate(rating="incorrect", reason="duplicate"),
        _user("admin"), db,
    )
    assert res["rating"] == "incorrect" and res["reason"] == "duplicate"


# ── upsert semantics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correction_rewrites_the_same_row():
    """One row per (event, user): a correction updates, never stacks."""
    ev = _event(None)
    admin = _user("admin")
    existing = _fb(ev.id, admin.id, rating="useful")
    db = FeedbackDB(
        responses=[FakeResult(scalar=existing)],
        objects={("Event", ev.id): ev, ("User", admin.id): admin},
    )
    res = await events_routes.set_event_feedback(
        ev.id, EventFeedbackCreate(rating="incorrect", reason="wrong_person"),
        admin, db,
    )
    assert res["rating"] == "incorrect"
    assert res["reason"] == "wrong_person"
    assert existing.rating == "incorrect"
    assert not db.added and db.commits == 1


@pytest.mark.asyncio
async def test_lost_insert_race_falls_back_to_update():
    ev = _event(None)
    admin = _user("admin")
    existing = _fb(ev.id, admin.id)
    db = FeedbackDB(
        responses=[_none_result(), FakeResult(scalar=existing)],
        objects={("Event", ev.id): ev, ("User", admin.id): admin},
    )

    async def exploding_commit():
        db.commits += 1
        if db.commits == 1:
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("dup", None, Exception())

    db.commit = exploding_commit
    res = await events_routes.set_event_feedback(
        ev.id, EventFeedbackCreate(rating="useful"), admin, db,
    )
    assert res["rating"] == "useful"
    assert db.rolled_back == 1


# ── listing and withdrawal ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_shows_every_reviewer():
    ev = _event(None)
    alice, bob = _user(), _user()
    rows = [_fb(ev.id, alice.id, "useful"), _fb(ev.id, bob.id, "incorrect", "timing")]
    db = FeedbackDB(
        responses=[FakeResult(rows=rows)],
        objects={
            ("Event", ev.id): ev,
            ("User", alice.id): SimpleNamespace(display_name="Alice", email="a@x"),
            ("User", bob.id): SimpleNamespace(display_name=None, email="b@x"),
        },
    )
    res = await events_routes.list_event_feedback(ev.id, _user(), db)
    assert [r["rating"] for r in res] == ["useful", "incorrect"]
    assert res[0]["reviewer_display_name"] == "Alice"
    # Fallback identity is the email, never a blank name.
    assert res[1]["reviewer_display_name"] == "b@x"


@pytest.mark.asyncio
async def test_withdraw_removes_only_the_callers_row():
    ev = _event(None)
    viewer = _user("admin")
    mine = _fb(ev.id, viewer.id)
    db = FeedbackDB(
        responses=[FakeResult(scalar=mine)],
        objects={("Event", ev.id): ev},
    )
    await events_routes.clear_event_feedback(ev.id, viewer, db)
    assert db.deleted == [mine]


@pytest.mark.asyncio
async def test_withdraw_without_feedback_is_404():
    ev = _event(None)
    db = FeedbackDB(responses=[_none_result()], objects={("Event", ev.id): ev})
    with pytest.raises(HTTPException) as exc:
        await events_routes.clear_event_feedback(ev.id, _user(), db)
    assert exc.value.status_code == 404


# ── summary metrics ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_reports_counts_and_response_rate():
    db = FeedbackDB(responses=[
        FakeResult(scalar=10),                                # events fired
        FakeResult(rows=[("useful", 6), ("incorrect", 2)]),   # ratings
        FakeResult(rows=[("duplicate", 2)]),                  # reasons
        FakeResult(scalar=4),                                 # distinct reviewed events
        FakeResult(scalar=2),                                 # distinct reviewers
    ])
    res = await events_routes.feedback_summary(hours=168, _current_user=_user("admin"), db=db)
    assert res["events_fired"] == 10
    assert res["events_reviewed"] == 4
    assert res["response_rate"] == 0.4
    assert res["distinct_reviewers"] == 2
    assert res["rating_counts"] == {
        "useful": 6, "correct_but_not_useful": 0, "incorrect": 2,
    }
    assert res["incorrect_reason_counts"]["duplicate"] == 2


@pytest.mark.asyncio
async def test_summary_with_no_events_has_no_rate():
    db = FeedbackDB(responses=[
        FakeResult(scalar=0),
        FakeResult(rows=[]),
        FakeResult(rows=[]),
        FakeResult(scalar=0),
        FakeResult(scalar=0),
    ])
    res = await events_routes.feedback_summary(hours=24, _current_user=_user("admin"), db=db)
    assert res["response_rate"] is None


# ── schema gating over HTTP ─────────────────────────────────────────


def test_reason_is_rejected_for_non_incorrect_ratings_over_http():
    """The two-interaction contract: a reason without 'incorrect' is a 422,
    not a silently dropped field."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.auth import get_current_user
    from shared.database import get_db

    app = FastAPI()
    app.include_router(events_routes.router, prefix="/api/events")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: _user("admin")
    try:
        client = TestClient(app, raise_server_exceptions=False)
        r = client.put(f"/api/events/{uuid.uuid4()}/feedback",
                       json={"rating": "useful", "reason": "duplicate"})
        assert r.status_code == 422
        # A valid body passes validation and reaches the route (500: no DB).
        r = client.put(f"/api/events/{uuid.uuid4()}/feedback",
                       json={"rating": "correct_but_not_useful"})
        assert r.status_code == 500
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
