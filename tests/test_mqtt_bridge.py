"""Tests for the MQTT bridge (services/integrations/mqtt/bridge.py)."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import aiomqtt
import pytest

from services.integrations.mqtt import bridge as bridge_module
from services.integrations.mqtt.bridge import MqttBridge
from services.integrations.mqtt.config import MqttConfig

CID = uuid.uuid4()


def make_camera(**over):
    cam = SimpleNamespace(
        id=CID, name="Front Door", enabled=True, detect_objects=True,
        recording_mode="always", status="live", display_order=0,
    )
    for k, v in over.items():
        setattr(cam, k, v)
    return cam


def make_cfg(**over):
    cfg = MqttConfig(enabled=True, host="broker", discovery_enabled=True)
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


class FakeClient:
    def __init__(self):
        self.published = []

    async def publish(self, topic, payload=None, qos=0, retain=False):
        data = payload if isinstance(payload, bytes) else str(payload).encode()
        self.published.append((str(topic), data, retain))


# ── config fingerprint ───────────────────────────────────────────────


def test_config_fingerprint_changes_on_connection_relevant_fields():
    base = make_cfg().fingerprint()
    assert make_cfg(host="other").fingerprint() != base
    assert make_cfg(prefix="campus").fingerprint() != base
    assert make_cfg(discovery_enabled=False).fingerprint() != base
    assert make_cfg().fingerprint() == base, "fingerprint must be stable for unchanged config"


# ── error classification ─────────────────────────────────────────────


def test_broker_error_group_is_classified_as_reconnectable():
    b = MqttBridge()
    group = ExceptionGroup("session", [aiomqtt.MqttError("connection lost")])
    b._classify_session_error(group)
    assert "connection lost" in (b.last_error or "")


def test_mixed_error_group_recorded_as_unexpected():
    b = MqttBridge()
    group = ExceptionGroup("session", [aiomqtt.MqttError("x"), ValueError("bug")])
    b._classify_session_error(group)
    assert b.last_error == "unexpected bridge error (see logs)"


def test_cancelled_error_propagates():
    b = MqttBridge()
    with pytest.raises(asyncio.CancelledError):
        b._classify_session_error(asyncio.CancelledError())


# ── announce ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_announce_publishes_discovery_and_state_mirrors():
    b = MqttBridge()
    client = FakeClient()
    slug = bridge_module.camera_slug("Front Door", CID)
    with patch.object(bridge_module, "_load_cameras", new=lambda: _async([make_camera()])):
        await b._announce(client, make_cfg(), force=True)

    topics = {t for t, _, _ in client.published}
    assert "homeassistant/sensor/nurby_stats/config" in topics
    assert f"homeassistant/binary_sensor/nurby_{CID}_motion/config" in topics
    assert f"homeassistant/event/nurby_{CID}_events/config" in topics
    assert f"homeassistant/camera/nurby_{CID}_camera/config" in topics
    for toggle in ("detect", "recordings", "enabled"):
        assert f"homeassistant/switch/nurby_{CID}_{toggle}/config" in topics
        assert (f"nurby/cameras/{slug}/{toggle}/state", b"ON", True) in client.published
    # Every discovery config is retained; slugs resolved for commands.
    for t, _, retain in client.published:
        assert retain is True
    assert b._slugs == {slug: str(CID)}
    assert b.announced_entities == len(b._announced) > 0


@pytest.mark.asyncio
async def test_announce_removes_gone_cameras():
    b = MqttBridge()
    client = FakeClient()
    with patch.object(bridge_module, "_load_cameras", new=lambda: _async([make_camera()])):
        await b._announce(client, make_cfg(), force=True)
    before = len(client.published)
    with patch.object(bridge_module, "_load_cameras", new=lambda: _async([])):
        await b._announce(client, make_cfg(), force=False)
    # Only teardown traffic after removal: empty retained payloads for the
    # old config topics, no state mirrors.
    after = client.published[before:]
    assert after and all(payload == b"" for _, payload, _ in after)
    assert all(retain for _, _, retain in after)
    # The hub stats sensor stays; only the camera's entities are torn down.
    assert b._announced == {"homeassistant/sensor/nurby_stats/config"}


@pytest.mark.asyncio
async def test_announce_skips_republish_when_unchanged():
    b = MqttBridge()
    client = FakeClient()
    with patch.object(bridge_module, "_load_cameras", new=lambda: _async([make_camera()])):
        await b._announce(client, make_cfg(), force=True)
        before = len(client.published)
        await b._announce(client, make_cfg(), force=False)
    new_topics = {t for t, _, _ in client.published[before:]}
    assert not any(t.startswith("homeassistant/") for t in new_topics)


@pytest.mark.asyncio
async def test_announce_with_discovery_disabled_blanks_previous_configs():
    b = MqttBridge()
    client = FakeClient()
    with patch.object(bridge_module, "_load_cameras", new=lambda: _async([make_camera()])):
        await b._announce(client, make_cfg(), force=True)
        before = len(client.published)
        await b._announce(client, make_cfg(discovery_enabled=False), force=False)
    teardown = client.published[before:]
    empty_configs = [(t, p) for t, p, r in teardown if p == b"" and t.startswith("homeassistant/")]
    assert empty_configs, "discovery off must blank previously announced configs"
    # State mirrors still flow with discovery off.
    assert any("/detect/state" in t for t, _, _ in teardown)


@pytest.mark.asyncio
async def test_inventory_change_detection_uses_fingerprint():
    b = MqttBridge()
    with patch.object(bridge_module, "_load_cameras", new=lambda: _async([make_camera()])):
        b._inventory_fingerprint = b._camera_fingerprint([make_camera()], make_cfg())
        assert await b._inventory_changed(make_cfg()) is False
        assert await b._inventory_changed(make_cfg(discovery_enabled=False)) is True


async def _async(value):
    return value
