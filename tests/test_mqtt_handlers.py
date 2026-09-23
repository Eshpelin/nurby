"""Tests for MQTT camera-toggle command handling (services/integrations/mqtt/handlers.py)."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.integrations.mqtt import handlers

CID = uuid.uuid4()
SLUG = "front-door-3f2a"


def fake_session_factory(camera):
    @asynccontextmanager
    async def factory():
        db = AsyncMock()
        db.get = AsyncMock(return_value=camera)
        yield db

    return factory


def make_camera(**over):
    cam = SimpleNamespace(
        id=CID, name="Front Door", enabled=True, detect_objects=True,
        recording_mode="always",
    )
    for k, v in over.items():
        setattr(cam, k, v)
    return cam


@pytest.fixture
def bus_capture():
    published = []

    async def fake_publish(topic, payload, retain=False):
        data = payload if isinstance(payload, bytes) else str(payload).encode()
        published.append((topic, data, retain))

    with patch.object(handlers, "mqtt_publish", new=fake_publish), \
         patch.object(handlers, "bus_redis") as redis_mock:
        redis_mock.return_value.set = AsyncMock()
        yield published, redis_mock.return_value


def db_session_patch(camera):
    return patch.object(handlers, "async_session", new=fake_session_factory(camera))


@pytest.mark.asyncio
async def test_detect_toggle_writes_column_and_mirrors_state(bus_capture):
    published, redis = bus_capture
    cam = make_camera(detect_objects=True)
    with db_session_patch(cam):
        state, error = await handlers.handle_command(CID, SLUG, "detect", b"OFF", "nurby")
    assert (state, error) == (False, "")
    assert cam.detect_objects is False
    # No stream restart for detect: perception picks it up from its
    # 30s camera-config cache.
    redis.set.assert_not_called()
    topic, payload, retain = published[-1]
    assert topic == f"nurby/cameras/{SLUG}/detect/state"
    assert payload == b"OFF" and retain is True


@pytest.mark.asyncio
async def test_recordings_off_maps_mode_and_signals_restart(bus_capture):
    published, redis = bus_capture
    cam = make_camera(recording_mode="always")
    with db_session_patch(cam):
        state, _ = await handlers.handle_command(CID, SLUG, "recordings", b"OFF", "nurby")
    assert state is False
    assert cam.recording_mode == "off"
    redis.set.assert_called_once_with(f"nurby:stream_restart:{CID}", "1")


@pytest.mark.asyncio
async def test_recordings_on_resumes_always(bus_capture):
    _, redis = bus_capture
    cam = make_camera(recording_mode="off")
    with db_session_patch(cam):
        state, _ = await handlers.handle_command(CID, SLUG, "recordings", b"ON", "nurby")
    assert state is True
    assert cam.recording_mode == "always"
    redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_enabled_toggle_signals_restart(bus_capture):
    _, redis = bus_capture
    cam = make_camera(enabled=True)
    with db_session_patch(cam):
        state, _ = await handlers.handle_command(CID, SLUG, "enabled", b"OFF", "nurby")
    assert state is False
    assert cam.enabled is False
    redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_unparsable_payload_rejected(bus_capture):
    published, _ = bus_capture
    state, error = await handlers.handle_command(CID, SLUG, "detect", b"MAYBE", "nurby")
    assert state is None
    assert "unparsable" in error
    assert published == []


@pytest.mark.asyncio
async def test_unknown_camera_rejected(bus_capture):
    published, _ = bus_capture
    with db_session_patch(None):
        state, error = await handlers.handle_command(CID, SLUG, "detect", b"ON", "nurby")
    assert state is None and "unknown camera" in error
    assert published == []


def test_parse_toggle_payload_dialects():
    assert handlers.parse_toggle_payload(b"ON") is True
    assert handlers.parse_toggle_payload("off") is False
    assert handlers.parse_toggle_payload(b"1") is True
    assert handlers.parse_toggle_payload("false") is False
    assert handlers.parse_toggle_payload(b" yes ") is True
    assert handlers.parse_toggle_payload(b"") is None
    assert handlers.parse_toggle_payload(b"open") is None
