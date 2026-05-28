import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.events import engine as engine_mod
from services.events.engine import RuleEngine


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        return _Result(self._rows)


def _patch_session(monkeypatch, rows):
    monkeypatch.setattr(engine_mod, "async_session", lambda: _Session(rows))


@pytest.mark.asyncio
async def test_attach_footage_links_recording(monkeypatch):
    rec = SimpleNamespace(id=uuid.uuid4())
    _patch_session(monkeypatch, [rec])
    data = {
        "camera_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await RuleEngine._attach_footage(data)
    assert data["recording_id"] == str(rec.id)
    assert f"/api/recordings/{rec.id}/stream" in data["recording_url"]


@pytest.mark.asyncio
async def test_attach_footage_no_match_leaves_empty(monkeypatch):
    _patch_session(monkeypatch, [])
    data = {
        "camera_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await RuleEngine._attach_footage(data)
    assert data["recording_id"] is None
    assert data["recording_url"] == ""


@pytest.mark.asyncio
async def test_attach_footage_idempotent(monkeypatch):
    rec = SimpleNamespace(id=uuid.uuid4())
    _patch_session(monkeypatch, [rec])
    data = {"recording_id": "already", "camera_id": str(uuid.uuid4()), "timestamp": "x"}
    await RuleEngine._attach_footage(data)
    assert data["recording_id"] == "already"  # untouched


@pytest.mark.asyncio
async def test_attach_footage_missing_fields_safe(monkeypatch):
    _patch_session(monkeypatch, [])
    data = {}
    await RuleEngine._attach_footage(data)
    assert data["recording_id"] is None
