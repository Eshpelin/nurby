"""Expected-activity CRUD API (#215): validation + permission scoping."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from services.api.routes import expected_activity as ea


def _run(coro):
    return asyncio.run(coro)


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), role="admin", is_active=True)


def _viewer(allowed_cams):
    # A selected-mode user; the mock DB below answers the ACL query.
    return SimpleNamespace(id=uuid.uuid4(), role="viewer", is_active=True,
                           camera_access_mode="selected", _allowed=allowed_cams)


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _DB:
    def __init__(self, rows=None, grants=None):
        self.rows = rows or []
        self.grants = grants or []
        self.added = []

    def add(self, o):
        self.added.append(o)

    async def commit(self):
        pass

    async def refresh(self, o):
        pass

    async def get(self, model, ident):
        return None

    async def execute(self, stmt):
        t = str(stmt).lower()
        if "from user_camera_access" in t:
            return _Res([(g,) for g in self.grants])
        return _Res(self.rows)


def _body(**kw):
    base = dict(
        name="Mom to kitchen", subject_kind="person", subject_key="Mom",
        camera_ids=[], weekdays=[0, 1, 2], start_time="09:00", end_time="10:00",
    )
    base.update(kw)
    return ea.ExpectedActivityBody(**base)


def test_create_person_requires_subject_key():
    with pytest.raises(Exception) as e:
        _run(ea.create_expected(_body(subject_kind="person", subject_key=None), _admin(), _DB()))
    assert "422" in str(e.value) or "subject_key" in str(e.value)


def test_create_rejects_bad_weekdays():
    with pytest.raises(Exception):
        _run(ea.create_expected(_body(weekdays=[]), _admin(), _DB()))
    with pytest.raises(Exception):
        _run(ea.create_expected(_body(weekdays=[9]), _admin(), _DB()))


def test_create_rejects_bad_mode():
    with pytest.raises(Exception):
        _run(ea.create_expected(_body(active_modes=["vacation"]), _admin(), _DB()))


def test_create_any_activity_ok_without_subject():
    out = _run(ea.create_expected(_body(subject_kind="any_activity", subject_key=None), _admin(), _DB()))
    assert out["subject_kind"] == "any_activity"
    assert out["subject_key"] is None


def test_create_foreign_camera_404_for_restricted_user():
    foreign = uuid.uuid4()
    granted = uuid.uuid4()
    user = _viewer([granted])
    db = _DB(grants=[granted])
    with pytest.raises(Exception) as e:
        _run(ea.create_expected(_body(camera_ids=[foreign]), user, db))
    assert "404" in str(e.value) or "not found" in str(e.value)


def test_list_hides_expectations_on_foreign_cameras():
    granted, foreign = uuid.uuid4(), uuid.uuid4()
    mine = SimpleNamespace(
        id=uuid.uuid4(), name="mine", subject_kind="any_activity", subject_key=None,
        camera_ids=[str(granted)], weekdays=[0], start_time="09:00", end_time="10:00",
        grace_minutes=30, active_modes=None, enabled=True, last_evaluated_on=None, last_status=None,
    )
    theirs = SimpleNamespace(
        id=uuid.uuid4(), name="theirs", subject_kind="any_activity", subject_key=None,
        camera_ids=[str(foreign)], weekdays=[0], start_time="09:00", end_time="10:00",
        grace_minutes=30, active_modes=None, enabled=True, last_evaluated_on=None, last_status=None,
    )
    user = _viewer([granted])
    db = _DB(rows=[mine, theirs], grants=[granted])
    out = _run(ea.list_expected(user, db))
    names = {r["name"] for r in out}
    assert "mine" in names and "theirs" not in names
