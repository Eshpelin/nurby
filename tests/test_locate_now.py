"""Tests for POST /search/locate-now — on-demand 'find X in this camera now'.

Calls the route handler directly with a fake DB session and mocked grounding,
so no app, no DB, no GPU.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api.routes.search import LocateNowRequest, locate_now


class _Result:
    def scalars(self):
        return self

    def __init__(self, obj):
        self._obj = obj

    def first(self):
        return self._obj


class _DB:
    def __init__(self, obs, cam):
        self._obs, self._cam = obs, cam

    async def execute(self, _q):
        return _Result(self._obs)

    async def get(self, _model, _id):
        return self._cam


def _obs(clean=None):
    return SimpleNamespace(
        id=uuid.uuid4(), thumbnail_path="thumb.jpg", clean_frame_path=clean,
        started_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
    )


def _enable(monkeypatch, enabled=True):
    async def _is_enabled():
        return enabled
    monkeypatch.setattr("services.grounding.config.is_enabled", _is_enabled)


def _mock_grounding(monkeypatch, boxes, error=None):
    box_objs = [SimpleNamespace(bbox_norm=b, is_point=False, label="chicken") for b in boxes]

    class _Client:
        async def ground(self, frame, prompt, interactive=False):
            return SimpleNamespace(boxes=box_objs, error=error)

    monkeypatch.setattr("services.grounding.client.get_client", lambda: _Client())
    monkeypatch.setattr("services.search.scan._default_frame_loader", lambda p: object())


_USER = SimpleNamespace(id=uuid.uuid4())


@pytest.mark.asyncio
async def test_locate_now_found(monkeypatch):
    _enable(monkeypatch)
    _mock_grounding(monkeypatch, [(0.1, 0.1, 0.3, 0.3)])
    obs = _obs()
    db = _DB(obs, SimpleNamespace(name="Front Door"))
    resp = await locate_now(
        LocateNowRequest(camera_id=uuid.uuid4(), prompt="chicken"), db=db, current_user=_USER,
    )
    assert resp.found is True
    assert len(resp.boxes) == 1 and resp.boxes[0]["label"] == "chicken"
    assert resp.observation_id == str(obs.id)
    assert resp.camera_name == "Front Door"


@pytest.mark.asyncio
async def test_locate_now_not_found(monkeypatch):
    _enable(monkeypatch)
    _mock_grounding(monkeypatch, [])
    db = _DB(_obs(), SimpleNamespace(name="Yard"))
    resp = await locate_now(
        LocateNowRequest(camera_id=uuid.uuid4(), prompt="zebra"), db=db, current_user=_USER,
    )
    assert resp.found is False and resp.boxes == []
    assert "No 'zebra'" in resp.summary


@pytest.mark.asyncio
async def test_locate_now_prefers_clean_frame(monkeypatch):
    _enable(monkeypatch)
    captured = {}

    class _Client:
        async def ground(self, frame, prompt, interactive=False):
            return SimpleNamespace(boxes=[], error=None)

    def _loader(path):
        captured["path"] = path
        return object()

    monkeypatch.setattr("services.grounding.client.get_client", lambda: _Client())
    monkeypatch.setattr("services.search.scan._default_frame_loader", _loader)
    db = _DB(_obs(clean="clean.jpg"), SimpleNamespace(name="X"))
    await locate_now(LocateNowRequest(camera_id=uuid.uuid4(), prompt="cat"), db=db, current_user=_USER)
    assert captured["path"] == "clean.jpg"  # grounded on the box-free frame


@pytest.mark.asyncio
async def test_locate_now_no_recent_frame(monkeypatch):
    _enable(monkeypatch)
    _mock_grounding(monkeypatch, [])
    db = _DB(None, SimpleNamespace(name="Garage"))  # no observation
    resp = await locate_now(
        LocateNowRequest(camera_id=uuid.uuid4(), prompt="cat"), db=db, current_user=_USER,
    )
    assert resp.found is False
    assert "No recent frame" in resp.summary


@pytest.mark.asyncio
async def test_locate_now_requires_prompt(monkeypatch):
    _enable(monkeypatch)
    db = _DB(_obs(), SimpleNamespace(name="X"))
    with pytest.raises(HTTPException) as ei:
        await locate_now(LocateNowRequest(camera_id=uuid.uuid4(), prompt="  "), db=db, current_user=_USER)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_locate_now_disabled(monkeypatch):
    _enable(monkeypatch, enabled=False)
    db = _DB(_obs(), SimpleNamespace(name="X"))
    with pytest.raises(HTTPException) as ei:
        await locate_now(LocateNowRequest(camera_id=uuid.uuid4(), prompt="chicken"), db=db, current_user=_USER)
    assert ei.value.status_code == 409
