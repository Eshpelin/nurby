"""Tests for producer-side MQTT publishers (services/integrations/mqtt/publishers.py)."""

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.integrations.mqtt import publishers


@pytest.fixture(autouse=True)
def _reset_publisher_state():
    publishers._motion_on.clear()
    publishers._last_motion.clear()
    publishers._slugs.clear()
    publishers._last_frame.clear()
    publishers._frame_interval = None
    yield
    publishers._motion_on.clear()
    publishers._last_motion.clear()
    publishers._slugs.clear()
    publishers._last_frame.clear()
    publishers._frame_interval = None


@pytest.fixture
def bus_capture():
    published = []

    async def fake_publish(topic, payload, retain=False):
        data = payload if isinstance(payload, bytes) else str(payload).encode()
        published.append((topic, data, retain))

    with patch.object(publishers, "mqtt_publish", new=fake_publish):
        yield published


CID = uuid.uuid4()


# ── event type mapping ───────────────────────────────────────────────


def test_map_event_type_person():
    et, label, conf = publishers.map_event_type(
        {"object_detections": {"objects": [{"label": "person", "confidence": 0.91}]}}
    )
    assert (et, label, conf) == ("person", "person", 0.91)


def test_map_event_type_vehicle_labels():
    for raw in ("car", "truck", "motorcycle"):
        et, label, _ = publishers.map_event_type(
            {"object_detections": {"objects": [{"label": raw, "confidence": 0.5}]}}
        )
        assert et == "vehicle" and label == raw


def test_map_event_type_unknown_label_maps_to_object():
    et, label, _ = publishers.map_event_type(
        {"object_detections": {"objects": [{"label": "backpack", "confidence": 0.4}]}}
    )
    assert (et, label) == ("object", "backpack")


def test_map_event_type_face_and_motion_fallbacks():
    assert publishers.map_event_type(
        {"person_detections": {"count": 1, "faces": [{"confidence": 0.8}]}}
    )[0] == "face"
    assert publishers.map_event_type({})[0] == "motion"


# ── rule event fan-out ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_rule_event_fans_out_three_messages(bus_capture):
    published = bus_capture
    rule = SimpleNamespace(id=uuid.uuid4(), name="Stranger alert")
    event_id = uuid.uuid4()
    obs = {
        "camera_id": str(CID),
        "camera_name": "Front Door",
        "timestamp": "2026-09-23T10:00:00+00:00",
        "object_detections": {"objects": [{"label": "person", "confidence": 0.9}]},
        "person_detections": {"count": 0},
        "thumbnail_path": None,
        "motion_score": 0.4,
        "observation_id": "obs-1",
    }
    ctx = {
        "event_id": str(event_id), "rule_id": str(rule.id), "rule_name": rule.name,
        "camera_id": str(CID), "camera_name": "Front Door", "timestamp": obs["timestamp"],
        "motion_score": 0.4, "object_detections": obs["object_detections"],
        "person_detections": obs["person_detections"], "vlm_description": "",
        "observation_id": "obs-1", "recording_id": "", "recording_url": "",
        "thumbnail_url": "", "event_url": "",
    }
    with patch("services.events.actions._build_template_context", return_value=ctx), \
         patch("services.events.actions._build_default_payload", return_value=dict(ctx)):
        await publishers.publish_rule_event(event_id, rule, obs, "alert")

    topics = [t for t, _, _ in published]
    assert topics[0] == "nurby/events"
    assert f"nurby/cameras/front-door-{str(CID)[:4]}/events" in topics
    # Event entity payload carries an announced HA event_type.
    events_payload = published[1][1]
    assert b'"event_type": "person"' in events_payload.replace(b": ", b": ") or \
        b'"event_type":"person"' in events_payload.replace(b": ", b":")


@pytest.mark.asyncio
async def test_publish_rule_event_never_raises(bus_capture):
    rule = SimpleNamespace(id=uuid.uuid4(), name="r")
    with patch("services.events.actions._build_template_context", side_effect=RuntimeError("boom")):
        await publishers.publish_rule_event(uuid.uuid4(), rule, {}, "alert")
    assert bus_capture == []


# ── motion edges ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_motion_on_edge_published_once(bus_capture):
    published = bus_capture
    publishers.set_camera_slug(CID, "front-door-3f2a")
    await publishers.note_motion(CID, "front-door-3f2a")
    await publishers.note_motion(CID, "front-door-3f2a")
    assert published == [("nurby/cameras/front-door-3f2a/motion", b"ON", False)]


@pytest.mark.asyncio
async def test_motion_off_after_quiet_delay(bus_capture):
    published = bus_capture
    publishers.set_camera_slug(CID, "front-door-3f2a")
    await publishers.note_motion(CID, "front-door-3f2a")
    # Simulate the last keyframe being older than the off-delay.
    publishers._last_motion[str(CID)] = time.monotonic() - publishers.MOTION_OFF_DELAY - 1
    await publishers.sweep_motion_off()
    assert published[-1] == ("nurby/cameras/front-door-3f2a/motion", b"OFF", False)
    # A sweep with no motion state does nothing.
    await publishers.sweep_motion_off()
    assert len(published) == 2


@pytest.mark.asyncio
async def test_prune_slugs_drops_gone_cameras(bus_capture):
    publishers.set_camera_slug(CID, "front-door-3f2a")
    await publishers.note_motion(CID, "front-door-3f2a")
    publishers.prune_slugs([])
    assert publishers.slug_for(CID) is None
    assert str(CID) not in publishers._motion_on


# ── periodic live frames ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_periodic_frame_rate_limited_and_encodable(bus_capture):
    published = bus_capture
    publishers.set_camera_slug(CID, "front-door-3f2a")
    publishers._frame_interval = 10  # skip the settings read
    encodes = []

    def encode(frame):
        encodes.append(frame)
        return b"jpeg-bytes"

    await publishers.maybe_publish_frame(CID, "frame-1", encode)
    await publishers.maybe_publish_frame(CID, "frame-2", encode)  # inside window
    assert encodes == ["frame-1"]
    assert published == [("nurby/cameras/front-door-3f2a/snapshot", b"jpeg-bytes", False)]


@pytest.mark.asyncio
async def test_periodic_frame_disabled_when_interval_zero(bus_capture):
    publishers.set_camera_slug(CID, "front-door-3f2a")
    publishers._frame_interval = 0
    await publishers.maybe_publish_frame(CID, "frame", lambda f: b"jpeg")
    assert bus_capture == []


@pytest.mark.asyncio
async def test_periodic_frame_skipped_without_slug(bus_capture):
    publishers._frame_interval = 10
    await publishers.maybe_publish_frame(CID, "frame", lambda f: b"jpeg")
    assert bus_capture == []
