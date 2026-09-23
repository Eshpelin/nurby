"""Camera isolation for the identity read surfaces (#201).

Extends ``test_camera_read_scope`` to the people / vehicle / journey
routes, which scan ``Observation`` (and linked incidents, transcripts and
recordings) for cross-camera presence and previously did so without a
per-user camera allowlist. Every SQL statement that touches a
camera-scoped table must carry the viewer's ``camera_id IN (...)``
predicate before it can return, aggregate, or feed a model.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from services.api.routes import journeys, persons, vehicles
from shared import auth
from shared.database import get_db
from shared.models import User


class _Empty:
    def scalars(self):
        return self

    def all(self):
        return []

    def first(self):
        return None

    def scalar_one_or_none(self):
        return None


def _fake_person(cam):
    return SimpleNamespace(
        id=uuid.uuid4(), display_name="Alice", nickname=None, relationship="resident",
        photo_path=None, is_starred=True, created_at=datetime.now(timezone.utc),
    )


def _fake_cluster():
    return SimpleNamespace(
        id=uuid.uuid4(), status="pending", sighting_count=3,
        last_seen_at=datetime.now(timezone.utc), first_seen_at=datetime.now(timezone.utc),
        first_camera_id=None, auto_label_number=645, appearance_description=None,
        appearance_description_status="pending", sample_thumbnail_path=None,
    )


def _fake_vehicle():
    return SimpleNamespace(
        id=uuid.uuid4(), identity_key="plate:ABC", display_name="Blue Van", nickname=None,
        license_plate="ABC123", vehicle_type="van", make="Ford", model="Transit",
        color="blue", description=None, is_starred=False, sighting_count=3,
        first_seen_at=None, last_seen_at=datetime.now(timezone.utc), first_camera_id=None,
    )


class IdentityDB:
    """Mock session that records compiled SQL and returns parent rows so the
    camera-scoped child scans actually execute (an empty parent would let a
    route short-circuit before the query we need to audit)."""

    def __init__(self):
        self.camera = uuid.uuid4()
        self.foreign_camera = uuid.uuid4()
        self.user = SimpleNamespace(
            id=uuid.uuid4(), role="viewer", is_active=True, camera_access_mode="selected",
        )
        self.statements = []

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()
        self.statements.append(sql)
        if "from user_camera_access" in sql:
            return SimpleNamespace(all=lambda: [(self.camera,)])
        if "from persons" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [_fake_person(self.camera)]))
        if "from vehicles" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [_fake_vehicle()]))
        if "from face_clusters" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [_fake_cluster()]))
        return _Empty()

    async def get(self, model, ident):
        if model is User:
            return self.user
        if model.__name__ == "Person":
            return _fake_person(self.camera)
        if model.__name__ == "Vehicle":
            return _fake_vehicle()
        if model.__name__ == "FaceCluster":
            return _fake_cluster()
        if model.__name__ == "Journey":
            # A journey whose only segment is on a foreign camera: the
            # segments-based scope check (#201) must hide it -> 404.
            return SimpleNamespace(
                id=ident, segments=[{"camera_id": str(self.foreign_camera)}],
            )
        return SimpleNamespace(id=ident, camera_id=self.foreign_camera)


@pytest.fixture
def http():
    db = IdentityDB()
    app = FastAPI()
    app.include_router(persons.router, prefix="/persons")
    app.include_router(vehicles.router, prefix="/vehicles")
    app.include_router(journeys.router, prefix="/journeys")

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {auth.create_access_token(db.user.id)}"
        yield client, db


# Paths whose camera-scoped scans must all carry the allowlist predicate.
SCOPED = [
    ("/persons/activity/summary", ["observations"]),
    ("/vehicles/activity/summary", ["observations"]),
    ("/vehicles/activity/" + str(uuid.uuid4()), ["observations"]),
    ("/persons/clusters/activity/summary", ["observations"]),
]


@pytest.mark.parametrize("path,tables", SCOPED)
def test_identity_scans_are_scoped(http, path, tables):
    client, db = http
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    for table in tables:
        stmts = [s for s in db.statements if f"from {table}" in s]
        assert stmts, (path, db.statements)
        for sql in stmts:
            assert f"{table}.camera_id in ('{db.camera}')" in sql, (path, sql)


@pytest.mark.parametrize("path", [
    "/persons/activity/" + str(uuid.uuid4()),
    "/persons/clusters/activity/" + str(uuid.uuid4()),
    "/persons/" + str(uuid.uuid4()) + "/photo-candidates",
])
def test_identity_feed_scans_are_scoped(http, path):
    client, db = http
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    obs = [s for s in db.statements if "from observations" in s]
    assert obs, db.statements
    for sql in obs:
        assert f"observations.camera_id in ('{db.camera}')" in sql


def test_follow_bundle_scopes_every_table(http):
    client, db = http
    resp = client.get("/persons/" + str(uuid.uuid4()) + "/follow")
    assert resp.status_code == 200, resp.text
    for table in ("observations", "incidents", "transcripts"):
        stmts = [s for s in db.statements if f"from {table}" in s]
        assert stmts, (table, db.statements)
        for sql in stmts:
            assert f"{table}.camera_id in ('{db.camera}')" in sql


def test_foreign_journey_detail_is_hidden(http):
    client, db = http
    resp = client.get("/journeys/" + str(uuid.uuid4()))
    # Journey row exists but every linked incident is out of scope → 404,
    # never confirming the id or leaking segments/transitions.
    assert resp.status_code == 404, resp.text


def test_no_access_user_sees_no_identity_rows(http):
    client, db = http
    db.user.camera_access_mode = "none"
    # An empty allowlist forces every scoped scan to a false predicate, so
    # nothing is returned. The exact rendering of an empty ``IN ()`` varies by
    # SQLAlchemy version, so we assert the positive allowlist is never present.
    assert client.get("/persons/activity/summary").status_code == 200
    assert client.get("/journeys").json() == []
    scoped = [s for s in db.statements if "from observations" in s or "from incidents" in s]
    assert scoped, db.statements
    for sql in scoped:
        assert f"camera_id in ('{db.camera}')" not in sql, sql
