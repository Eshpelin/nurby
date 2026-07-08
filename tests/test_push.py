"""Mobile push notifications. Device registry routes + FCM dispatcher.

Covers:
1. Model surface: PushDevice unique token, cascade-delete FK.
2. Routes: register upserts by token (re-assigning to the current user),
   list is scoped to the caller, delete is own-devices-only (404 for
   anyone else's), /test reports {sent, errors}, /config exposes the
   client config but never the service account.
3. Dispatcher: unconfigured installs no-op, the configured path sends
   over the mocked FCM seam, UNREGISTERED/404 tokens are pruned, and
   nothing ever raises into the caller.
4. Hooks: the notification-creation paths (rule notify action, report
   scheduler) fan out to push best-effort.

The suite has no live DB (repo convention): route handlers are invoked
directly with fake sessions, and the FCM HTTP call is monkeypatched at
the shared.push._fcm_send seam (mirrors the deliver_signed seam in the
webhook tests).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from services.api.routes import push as push_routes
from shared import push as push_mod
from shared.models import PushDevice


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


def _device(user_id=None, **kwargs) -> PushDevice:
    """Bare PushDevice instance (no DB) with required attrs filled."""
    now = datetime.now(timezone.utc)
    return PushDevice(
        id=kwargs.get("id", uuid.uuid4()),
        user_id=user_id or uuid.uuid4(),
        platform=kwargs.get("platform", "android"),
        token=kwargs.get("token", f"tok-{uuid.uuid4()}"),
        app_version=kwargs.get("app_version", "1.0.0"),
        created_at=kwargs.get("created_at", now),
        last_seen_at=kwargs.get("last_seen_at", now),
    )


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Just enough AsyncSession surface for the push routes/dispatcher."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.stmts = []
        self.added = []
        self.deleted = []
        self.commits = 0
        self.get_result = None

    async def execute(self, stmt):
        self.stmts.append(stmt)
        return _Result(self.rows)

    async def get(self, model, ident):
        return self.get_result

    def add(self, row):
        self.added.append(row)

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.commits += 1

    async def refresh(self, row):
        # Emulate the server-side defaults a real flush would fill in.
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(row, "created_at", None) is None:
            row.created_at = now
        if getattr(row, "last_seen_at", None) is None:
            row.last_seen_at = now


def _user(role="viewer"):
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)


def _configure(monkeypatch, *, service_account=None, client_config=None):
    """Point both get_setting seams (dispatcher + routes) at fixed values."""
    values = {
        "push_fcm_service_account": service_account,
        "push_firebase_client_config": client_config,
    }

    async def fake_get_setting(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr(push_mod, "get_setting", fake_get_setting)
    monkeypatch.setattr(push_routes, "get_setting", fake_get_setting)


_SA = {"project_id": "demo-project", "client_email": "svc@demo.iam", "private_key": "k"}


# ---------------------------------------------------------------------------
# 1. Model surface
# ---------------------------------------------------------------------------


def test_model_token_is_unique_text():
    col = PushDevice.__table__.columns["token"]
    assert col.unique is True
    assert col.nullable is False


def test_model_user_fk_cascades():
    fk = next(iter(PushDevice.__table__.columns["user_id"].foreign_keys))
    assert fk.ondelete == "CASCADE"
    assert fk.column.table.name == "users"


def test_model_platform_and_timestamps():
    cols = PushDevice.__table__.columns
    assert cols["platform"].nullable is False
    assert cols["app_version"].nullable is True
    assert cols["last_seen_at"].nullable is False


# ---------------------------------------------------------------------------
# 2. Routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_creates_new_device():
    user = _user()
    db = _FakeDB(rows=[])  # no existing row for this token
    body = push_routes.DeviceRegister(platform="ios", token="tok-1", app_version="2.1.0")

    out = await push_routes.register_device(body, user, db)

    assert len(db.added) == 1
    row = db.added[0]
    assert row.user_id == user.id
    assert row.platform == "ios"
    assert row.token == "tok-1"
    assert row.app_version == "2.1.0"
    assert db.commits == 1
    assert out.token == "tok-1"
    # Lookup must have filtered by token.
    assert "push_devices.token" in _sql(db.stmts[0])


@pytest.mark.asyncio
async def test_register_existing_token_reassigns_to_current_user():
    old_owner = uuid.uuid4()
    existing = _device(
        user_id=old_owner,
        token="tok-shared",
        platform="ios",
        last_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    user = _user()
    db = _FakeDB(rows=[existing])
    body = push_routes.DeviceRegister(platform="android", token="tok-shared")

    out = await push_routes.register_device(body, user, db)

    assert db.added == []  # upsert, not a duplicate row
    assert existing.user_id == user.id
    assert existing.platform == "android"
    assert existing.last_seen_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
    # app_version omitted -> keep the stored one.
    assert existing.app_version == "1.0.0"
    assert db.commits == 1
    assert out.id == existing.id


@pytest.mark.asyncio
async def test_list_devices_queries_only_own():
    user = _user()
    mine = _device(user_id=user.id)
    db = _FakeDB(rows=[mine])

    out = await push_routes.list_devices(user, db)

    assert [d.id for d in out] == [mine.id]
    sql = _sql(db.stmts[0])
    assert f"push_devices.user_id = '{user.id}'" in sql


@pytest.mark.asyncio
async def test_delete_own_device():
    user = _user()
    row = _device(user_id=user.id)
    db = _FakeDB()
    db.get_result = row

    await push_routes.delete_device(row.id, user, db)

    assert db.deleted == [row]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_delete_other_users_device_404():
    user = _user()
    row = _device(user_id=uuid.uuid4())  # someone else's
    db = _FakeDB()
    db.get_result = row

    with pytest.raises(HTTPException) as exc_info:
        await push_routes.delete_device(row.id, user, db)

    assert exc_info.value.status_code == 404
    assert db.deleted == []


@pytest.mark.asyncio
async def test_delete_missing_device_404():
    db = _FakeDB()
    db.get_result = None
    with pytest.raises(HTTPException) as exc_info:
        await push_routes.delete_device(uuid.uuid4(), _user(), db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_test_endpoint_reports_sent_and_errors(monkeypatch):
    user = _user()
    recorder = AsyncMock(return_value={"sent": 2, "errors": ["dev-x: boom"]})
    monkeypatch.setattr(push_routes, "send_push_to_user", recorder)

    out = await push_routes.send_test_push(user, _FakeDB())

    assert out == {"sent": 2, "errors": ["dev-x: boom"]}
    assert recorder.await_args.args[1] == user.id  # targets the caller only


@pytest.mark.asyncio
async def test_test_endpoint_unconfigured(monkeypatch):
    recorder = AsyncMock(return_value={"sent": 0, "skipped": True})
    monkeypatch.setattr(push_routes, "send_push_to_user", recorder)
    out = await push_routes.send_test_push(_user(), _FakeDB())
    assert out["sent"] == 0
    assert out["errors"]  # tells the caller push is not configured


@pytest.mark.asyncio
async def test_config_configured(monkeypatch):
    web = {"apiKey": "k", "appId": "a", "projectId": "demo-project", "messagingSenderId": "42"}
    _configure(monkeypatch, service_account=_SA, client_config=web)

    out = await push_routes.get_push_config(_user())

    assert out == {"configured": True, "firebase_web_config": web}
    # The service account must never leak through this endpoint.
    assert "private_key" not in str(out["firebase_web_config"])


@pytest.mark.asyncio
async def test_config_unconfigured(monkeypatch):
    _configure(monkeypatch)
    out = await push_routes.get_push_config(_user())
    assert out == {"configured": False, "firebase_web_config": None}


def test_service_account_absent_from_settings_response():
    """GET /api/system/settings must not echo the pasted private key."""
    from shared.schemas import SystemSettingsResponse, SystemSettingsUpdate

    assert "push_fcm_service_account" not in SystemSettingsResponse.model_fields
    assert "push_firebase_client_config" in SystemSettingsResponse.model_fields
    # ...but both keys are PATCHable.
    assert "push_fcm_service_account" in SystemSettingsUpdate.model_fields
    assert "push_firebase_client_config" in SystemSettingsUpdate.model_fields

    from services.api.routes.system import SETTINGS_WHITELIST

    assert "push_fcm_service_account" in SETTINGS_WHITELIST
    assert "push_firebase_client_config" in SETTINGS_WHITELIST


# ---------------------------------------------------------------------------
# 3. Dispatcher
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    push_mod._reset_token_cache()
    yield
    push_mod._reset_token_cache()


def _mint_ok(monkeypatch):
    monkeypatch.setattr(
        push_mod, "_mint_access_token", lambda sa: ("fcm-access-token", time.time() + 3600)
    )


@pytest.mark.asyncio
async def test_dispatch_unconfigured_noops(monkeypatch):
    _configure(monkeypatch, service_account=None)
    db = _FakeDB(rows=[_device()])

    out = await push_mod.send_push_to_user(db, uuid.uuid4(), "t", "b", {})

    assert out == {"sent": 0, "skipped": True}
    assert db.stmts == []  # never even queried devices


@pytest.mark.asyncio
async def test_dispatch_sends_to_all_user_devices(monkeypatch):
    _configure(monkeypatch, service_account=_SA)
    _mint_ok(monkeypatch)
    sends = []

    async def fake_fcm_send(access_token, project_id, message):
        sends.append((access_token, project_id, message))
        return 200, {"name": "projects/demo-project/messages/1"}

    monkeypatch.setattr(push_mod, "_fcm_send", fake_fcm_send)

    uid = uuid.uuid4()
    devices = [_device(user_id=uid, token="tok-a"), _device(user_id=uid, token="tok-b")]
    db = _FakeDB(rows=devices)

    out = await push_mod.send_push_to_user(db, uid, "Alert", "Person at door", {"count": 7})

    assert out == {"sent": 2, "errors": []}
    assert {s[2]["token"] for s in sends} == {"tok-a", "tok-b"}
    assert sends[0][0] == "fcm-access-token"
    assert sends[0][1] == "demo-project"
    assert sends[0][2]["notification"] == {"title": "Alert", "body": "Person at door"}
    assert sends[0][2]["data"] == {"count": "7"}  # FCM data must be strings
    # Device query was scoped to the user.
    assert f"push_devices.user_id = '{uid}'" in _sql(db.stmts[0])
    assert db.deleted == []


@pytest.mark.asyncio
async def test_dispatch_user_none_fans_out_unfiltered(monkeypatch):
    _configure(monkeypatch, service_account=_SA)
    _mint_ok(monkeypatch)
    monkeypatch.setattr(push_mod, "_fcm_send", AsyncMock(return_value=(200, {})))
    db = _FakeDB(rows=[_device(), _device()])

    out = await push_mod.send_push_to_user(db, None, "t", "b")

    assert out["sent"] == 2
    assert "push_devices.user_id =" not in _sql(db.stmts[0])


@pytest.mark.asyncio
async def test_dispatch_prunes_unregistered_tokens(monkeypatch):
    _configure(monkeypatch, service_account=_SA)
    _mint_ok(monkeypatch)
    uid = uuid.uuid4()
    dead_404 = _device(user_id=uid, token="tok-dead")
    dead_unreg = _device(user_id=uid, token="tok-unreg")
    alive = _device(user_id=uid, token="tok-alive")

    async def fake_fcm_send(access_token, project_id, message):
        if message["token"] == "tok-dead":
            return 404, {"error": {"status": "NOT_FOUND", "message": "unregistered"}}
        if message["token"] == "tok-unreg":
            return 400, {
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "details": [{"errorCode": "UNREGISTERED"}],
                }
            }
        return 200, {}

    monkeypatch.setattr(push_mod, "_fcm_send", fake_fcm_send)
    db = _FakeDB(rows=[dead_404, dead_unreg, alive])

    out = await push_mod.send_push_to_user(db, uid, "t", "b")

    assert out == {"sent": 1, "errors": []}  # dead tokens are pruned, not errors
    assert set(db.deleted) == {dead_404, dead_unreg}
    assert db.commits == 1


@pytest.mark.asyncio
async def test_dispatch_collects_errors_without_raising(monkeypatch):
    _configure(monkeypatch, service_account=_SA)
    _mint_ok(monkeypatch)
    uid = uuid.uuid4()
    d1 = _device(user_id=uid, token="tok-500")
    d2 = _device(user_id=uid, token="tok-raise")

    async def fake_fcm_send(access_token, project_id, message):
        if message["token"] == "tok-500":
            return 500, {"error": {"message": "backend exploded"}}
        raise RuntimeError("network down")

    monkeypatch.setattr(push_mod, "_fcm_send", fake_fcm_send)
    db = _FakeDB(rows=[d1, d2])

    out = await push_mod.send_push_to_user(db, uid, "t", "b")

    assert out["sent"] == 0
    assert len(out["errors"]) == 2
    assert any("backend exploded" in e for e in out["errors"])
    assert db.deleted == []  # transient failures never prune


@pytest.mark.asyncio
async def test_dispatch_token_mint_failure_is_soft(monkeypatch):
    _configure(monkeypatch, service_account=_SA)

    def broken_mint(sa):
        raise RuntimeError("bad service account")

    monkeypatch.setattr(push_mod, "_mint_access_token", broken_mint)
    db = _FakeDB(rows=[_device()])

    out = await push_mod.send_push_to_user(db, None, "t", "b")

    assert out == {"sent": 0, "errors": ["could not mint an FCM access token"]}


@pytest.mark.asyncio
async def test_dispatch_never_raises_even_on_session_crash(monkeypatch):
    _configure(monkeypatch, service_account=_SA)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    out = await push_mod.send_push_to_user(db, uuid.uuid4(), "t", "b")

    assert out["sent"] == 0
    assert out["errors"]


@pytest.mark.asyncio
async def test_dispatch_no_devices_is_clean_zero(monkeypatch):
    _configure(monkeypatch, service_account=_SA)
    out = await push_mod.send_push_to_user(_FakeDB(rows=[]), uuid.uuid4(), "t", "b")
    assert out == {"sent": 0, "errors": []}


def test_is_unregistered_matrix():
    assert push_mod._is_unregistered(404, {}) is True
    assert push_mod._is_unregistered(400, {"error": {"status": "NOT_FOUND"}}) is True
    assert (
        push_mod._is_unregistered(
            400, {"error": {"details": [{"errorCode": "UNREGISTERED"}]}}
        )
        is True
    )
    assert push_mod._is_unregistered(400, {"error": {"status": "INVALID_ARGUMENT"}}) is False
    assert push_mod._is_unregistered(500, {}) is False


# ---------------------------------------------------------------------------
# 4. Notification-creation hooks
# ---------------------------------------------------------------------------


class _HookSession:
    """Async-context-manager session for the notify persistence path."""

    def __init__(self):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass

    async def refresh(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()


@pytest.mark.asyncio
async def test_notify_action_dispatches_push(monkeypatch):
    from services.events import actions as actions_mod

    monkeypatch.setattr(actions_mod, "async_session", lambda: _HookSession())
    monkeypatch.setattr("services.api.ws.broadcast", AsyncMock())
    monkeypatch.setattr(actions_mod, "_update_event_status", AsyncMock())
    recorder = AsyncMock(return_value={"sent": 1, "errors": []})
    monkeypatch.setattr("shared.push.send_push_to_user", recorder)

    rule = SimpleNamespace(id=uuid.uuid4(), name="Person at door")
    event_id = uuid.uuid4()
    data = {"camera_id": str(uuid.uuid4()), "timestamp": "2026-07-08T00:00:00+00:00"}
    action = {"type": "notify", "message": "Someone is at the front door", "severity": "warning"}

    await actions_mod._execute_notify(action, data, rule, event_id, {"rule_name": rule.name})

    assert recorder.await_count == 1
    args = recorder.await_args
    assert args.args[1] is None  # household-wide fan-out
    assert args.kwargs["body"] == "Someone is at the front door"
    assert args.kwargs["title"] == "Nurby: Person at door"
    assert args.kwargs["data"]["event_id"] == str(event_id)


@pytest.mark.asyncio
async def test_notify_action_survives_push_failure(monkeypatch):
    """A crashing push layer must not fail the notify action."""
    from services.events import actions as actions_mod

    broadcaster = AsyncMock()
    status = AsyncMock()
    monkeypatch.setattr(actions_mod, "async_session", lambda: _HookSession())
    monkeypatch.setattr("services.api.ws.broadcast", broadcaster)
    monkeypatch.setattr(actions_mod, "_update_event_status", status)
    monkeypatch.setattr(
        "shared.push.send_push_to_user", AsyncMock(side_effect=RuntimeError("push exploded"))
    )

    rule = SimpleNamespace(id=uuid.uuid4(), name="r")
    await actions_mod._execute_notify(
        {"type": "notify", "message": "m"}, {"camera_id": str(uuid.uuid4())}, rule, uuid.uuid4(), {}
    )

    # The in-app notification still went out and the action still succeeded.
    broadcaster.assert_awaited_once()
    assert status.await_args.args[2] == "success"


@pytest.mark.asyncio
async def test_report_delivery_dispatches_push(monkeypatch):
    from services.api import report_scheduler as rs

    monkeypatch.setattr(rs, "async_session", lambda: _HookSession())
    monkeypatch.setattr("services.api.ws.broadcast", AsyncMock())
    recorder = AsyncMock(return_value={"sent": 1, "errors": []})
    monkeypatch.setattr("shared.push.send_push_to_user", recorder)

    report = SimpleNamespace(id=uuid.uuid4(), name="Morning recap", delivery={"notify": True})
    await rs._deliver(report, "All quiet overnight.")

    assert recorder.await_count == 1
    args = recorder.await_args
    assert args.args[1] is None
    assert args.kwargs["title"] == "Nurby report: Morning recap"
    assert args.kwargs["body"] == "All quiet overnight."


@pytest.mark.asyncio
async def test_guardian_delivery_counts_push(monkeypatch):
    from services.guardian import delivery

    uid = uuid.uuid4()
    user = SimpleNamespace(id=uid, email=None)
    db = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=res)
    db.get = AsyncMock(return_value=user)

    recorder = AsyncMock(return_value={"sent": 2, "errors": []})
    monkeypatch.setattr("shared.push.send_push_to_user", recorder)

    link = SimpleNamespace(id=uuid.uuid4(), guardian_user_id=uid, notify_channels=None)
    out = await delivery.deliver_to_guardians(db, [link], message="Dad may have fallen")

    assert out["push_sent"] == 2
    assert recorder.await_args.args[1] == uid
