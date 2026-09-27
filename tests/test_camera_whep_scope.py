"""Camera-scoped WHEP signaling never forwards a foreign camera path."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routes import cameras
from shared import auth
from shared.database import get_db
from shared.models import Camera, User


class _Result:
    def __init__(self, rows=()):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _DB:
    def __init__(self):
        self.allowed_camera = uuid.uuid4()
        self.foreign_camera = uuid.uuid4()
        self.user = SimpleNamespace(
            id=uuid.uuid4(), role="viewer", is_active=True, camera_access_mode="selected"
        )
        self.camera = SimpleNamespace(
            id=self.allowed_camera,
            stream_type="rtsp",
            stream_url="rtsp://camera/stream",
            webcam_device=None,
        )

    async def execute(self, statement):
        if "user_camera_access" in str(statement).lower():
            return _Result([(self.allowed_camera,)])
        return _Result()

    async def get(self, model, ident):
        if model is User:
            return self.user if ident == self.user.id else None
        if model is Camera:
            return self.camera if ident == self.allowed_camera else None
        return None


def _client(db):
    app = FastAPI()
    app.include_router(cameras.router, prefix="/cameras")

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {auth.create_access_token(db.user.id)}"
    return client


def test_whep_rejects_foreign_camera_before_relay(monkeypatch):
    db = _DB()
    relay = AsyncMock()
    monkeypatch.setattr(cameras.httpx, "AsyncClient", relay)

    with _client(db) as client:
        response = client.post(f"/cameras/{db.foreign_camera}/whep", content="offer")

    assert response.status_code == 404
    relay.assert_not_awaited()


def test_whep_forwards_only_an_authorized_camera(monkeypatch):
    db = _DB()

    class _RelayResponse:
        status_code = 201
        content = b"answer"
        headers = {"content-type": "application/sdp"}

    class _RelayClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            assert url.endswith(f"/cam-{db.allowed_camera}/whep")
            assert kwargs["content"] == b"offer"
            return _RelayResponse()

    monkeypatch.setattr(cameras.httpx, "AsyncClient", lambda **kwargs: _RelayClient())
    with _client(db) as client:
        response = client.post(f"/cameras/{db.allowed_camera}/whep", content=b"offer")

    assert response.status_code == 201
    assert response.content == b"answer"


def test_hls_rejects_foreign_camera_before_relay(monkeypatch):
    db = _DB()
    relay = AsyncMock()
    monkeypatch.setattr(cameras.httpx, "AsyncClient", relay)

    with _client(db) as client:
        response = client.get(f"/cameras/{db.foreign_camera}/hls/index.m3u8")

    assert response.status_code == 404
    relay.assert_not_awaited()
