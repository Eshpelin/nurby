"""Permission transitions, safe migration and live-session revocation (#190)."""

import importlib.util
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.api import ws
from services.api.routes import users
from shared.camera_access import ALL, allowed_camera_ids
from shared.models import Camera, User
from shared.schemas import SetCameraAccessRequest, UserUpdate


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class AccessDB:
    def __init__(self, mode="selected", camera=None):
        self.user = SimpleNamespace(id=uuid.uuid4(), role="viewer", is_active=True, camera_access_mode=mode)
        self.camera = SimpleNamespace(id=camera or uuid.uuid4())
        self.grants = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.flush = AsyncMock()

    async def get(self, model, key, **kwargs):
        if model is User:
            return self.user if key == self.user.id else None
        if model is Camera:
            return self.camera if key == self.camera.id else None

    async def execute(self, statement):
        sql = str(statement)
        if sql.startswith("SELECT user_camera_access.camera_id"):
            return Result([(g.camera_id,) for g in self.grants])
        return Result(list(self.grants))

    async def delete(self, row):
        self.grants.remove(row)

    def add(self, row):
        self.grants.append(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", None, "unexpected"])
async def test_non_selected_policy_denies_even_stale_grants(mode):
    db = AccessDB(mode)
    db.grants = [SimpleNamespace(camera_id=db.camera.id)]
    assert await allowed_camera_ids(db.user, db) == set()


@pytest.mark.asyncio
async def test_missing_mode_fails_closed():
    db = AccessDB()
    del db.user.camera_access_mode
    assert await allowed_camera_ids(db.user, db) == set()


@pytest.mark.asyncio
async def test_explicit_all_includes_future_cameras():
    db = AccessDB("all")
    assert await allowed_camera_ids(db.user, db) is ALL


@pytest.mark.asyncio
async def test_grant_then_final_revoke_denies_camera_and_foreign_camera():
    db = AccessDB("none")
    await users.grant_camera_access(db.user.id, db.camera.id, admin=db.user, db=db)
    assert await allowed_camera_ids(db.user, db) == {db.camera.id}
    await users.revoke_camera_access(db.user.id, db.camera.id, admin=db.user, db=db)
    assert db.user.camera_access_mode == "selected"
    assert await allowed_camera_ids(db.user, db) == set()


@pytest.mark.asyncio
async def test_bulk_empty_replaces_explicit_all_with_no_access():
    db = AccessDB("all")
    await users.set_user_cameras(db.user.id, SetCameraAccessRequest(camera_ids=[]), admin=db.user, db=db)
    assert db.user.camera_access_mode == "none"
    assert await allowed_camera_ids(db.user, db) == set()


@pytest.mark.asyncio
async def test_single_grant_does_not_silently_narrow_explicit_all():
    db = AccessDB("all")
    with pytest.raises(HTTPException) as exc:
        await users.grant_camera_access(db.user.id, db.camera.id, admin=db.user, db=db)
    assert exc.value.status_code == 409
    assert await allowed_camera_ids(db.user, db) is ALL


@pytest.mark.asyncio
async def test_invalid_replacement_preserves_previous_grants():
    db = AccessDB()
    grant = SimpleNamespace(camera_id=db.camera.id)
    db.grants = [grant]
    with pytest.raises(HTTPException) as exc:
        await users.set_user_cameras(
            db.user.id, SetCameraAccessRequest(camera_ids=[uuid.uuid4()]), admin=db.user, db=db,
        )
    assert exc.value.status_code == 404
    assert db.grants == [grant]
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_grants_deduplicate_ids():
    db = AccessDB("none")
    await users.set_user_cameras(
        db.user.id, SetCameraAccessRequest(camera_ids=[db.camera.id, db.camera.id]), admin=db.user, db=db,
    )
    assert len(db.grants) == 1
    assert await allowed_camera_ids(db.user, db) == {db.camera.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["all", "none"])
async def test_explicit_policy_change_clears_stale_grants(mode):
    db = AccessDB()
    db.grants = [SimpleNamespace(camera_id=db.camera.id)]
    await users.update_user(db.user.id, UserUpdate(camera_access_mode=mode), admin=db.user, db=db)
    assert db.grants == []
    assert db.user.camera_access_mode == mode


def test_invalid_policy_rejected():
    for value in [None, "", "unrestricted"]:
        with pytest.raises(ValidationError):
            UserUpdate(camera_access_mode=value)
    assert UserUpdate().model_dump(exclude_unset=True) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["revoked", "deactivated", "database"])
async def test_connected_socket_does_not_keep_stale_access(monkeypatch, failure):
    db = AccessDB("none")
    # A hashable fake socket with the real send_text contract.
    class Socket:
        send_text = AsyncMock()
    socket = Socket()
    monkeypatch.setattr(ws, "_connections", {socket: ALL})
    monkeypatch.setattr(ws, "_connection_users", {socket: db.user.id})
    if failure == "deactivated":
        db.user.is_active = False

    @asynccontextmanager
    async def session():
        if failure == "database":
            raise RuntimeError("database unavailable")
        yield db

    monkeypatch.setattr(ws, "async_session", session)
    await ws._deliver_local('{"type":"event","camera_id":"' + str(db.camera.id) + '"}')
    socket.send_text.assert_not_awaited()


def test_migration_preserves_old_scope_and_defaults_new_accounts_to_none(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/f9c2d4e6a8b0_explicit_camera_access.py"
    spec = importlib.util.spec_from_file_location("explicit_access_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Execute the actual backfill SQL against representative legacy rows.
    # PostgreSQL DDL is separately checked by Alembic's offline generation.
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE users (id TEXT, role TEXT)")
        conn.execute("CREATE TABLE user_camera_access (user_id TEXT, camera_id TEXT)")
        conn.executemany("INSERT INTO users VALUES (?, ?)", [("a", "admin"), ("b", "viewer"), ("c", "viewer")])
        conn.execute("INSERT INTO user_camera_access VALUES ('c', 'camera')")

        def add_column(table, column):
            assert column.server_default.arg == "none"
            conn.execute("ALTER TABLE users ADD COLUMN camera_access_mode TEXT NOT NULL DEFAULT 'none'")

        monkeypatch.setattr(migration, "op", SimpleNamespace(
            add_column=add_column, execute=conn.execute, create_check_constraint=lambda *args: None,
        ))
        migration.upgrade()
        assert dict(conn.execute("SELECT id, camera_access_mode FROM users")) == {
            "a": "all", "b": "all", "c": "selected",
        }
        conn.execute("INSERT INTO users (id, role) VALUES ('new', 'viewer')")
        assert conn.execute("SELECT camera_access_mode FROM users WHERE id = 'new'").fetchone() == ("none",)
    with pytest.raises(RuntimeError, match="cannot be safely downgraded"):
        migration.downgrade()
