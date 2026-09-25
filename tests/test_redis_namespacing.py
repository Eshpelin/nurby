"""Per-install Redis namespacing (#291).

Two Nurby stacks sharing one Redis server used to relay each other's live
alerts, cross-drain each other's heartbeat and health keys, and read each
other's camera-status stream, because every shared name was a fixed
literal. All instance-shared names now come from shared.redis_keys and
embed the install namespace. The relay/bridge/invalidate listeners keep
subscribing to the legacy channels for one release so a rolling update
doesn't silently drop messages from pre-update processes.
"""

import importlib

import pytest


@pytest.fixture(autouse=True)
def clean_instance_env(monkeypatch):
    monkeypatch.delenv("NURBY_INSTANCE_ID", raising=False)
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    yield


def test_namespace_resolution_order():
    import shared.redis_keys as rk

    assert rk.instance_namespace() == "nurby"  # safe default
    monkey_ns = pytest.MonkeyPatch()
    monkey_ns.setenv("COMPOSE_PROJECT_NAME", "nurby-backend")
    assert rk.instance_namespace() == "nurby-backend"
    monkey_ns.setenv("NURBY_INSTANCE_ID", "qa-1")
    assert rk.instance_namespace() == "qa-1"  # explicit wins over compose
    monkey_ns.undo()


def test_namespace_is_a_safe_key_fragment(monkeypatch):
    import shared.redis_keys as rk

    monkeypatch.setenv("NURBY_INSTANCE_ID", "weird project/name!")
    assert rk.instance_namespace() == "weird-project-name-"
    assert ":" not in rk.instance_namespace()


def test_shared_names_embed_the_namespace(monkeypatch):
    monkeypatch.setenv("NURBY_INSTANCE_ID", "qa-1")
    import shared.redis_keys as rk

    assert rk.ws_broadcast_channel() == "qa-1:ws:broadcast"
    assert rk.mqtt_bus_channel() == "qa-1:mqtt:out"
    assert rk.rules_invalidate_channel() == "qa-1:rules:invalidate"
    assert rk.heartbeat_key("ingestion") == "qa-1:heartbeat:ingestion"
    assert rk.health_key("vlm") == "qa-1:health:vlm"
    assert rk.camera_status_stream_key() == "qa-1:camera_status"


def test_module_constants_recompute_with_environment(monkeypatch):
    """Producers/consumers import module-level constants; the namespace is
    process-stable, but tests must be able to exercise both values."""
    import shared.redis_keys as rk

    monkeypatch.setenv("NURBY_INSTANCE_ID", "qa-1")
    importlib.reload(rk)
    assert rk.CAMERA_STATUS_STREAM_KEY == "qa-1:camera_status"
    monkeypatch.delenv("NURBY_INSTANCE_ID")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "nurby-backend")
    importlib.reload(rk)
    assert rk.CAMERA_STATUS_STREAM_KEY == "nurby-backend:camera_status"
    monkeypatch.delenv("COMPOSE_PROJECT_NAME")
    importlib.reload(rk)
    assert rk.CAMERA_STATUS_STREAM_KEY == "nurby:camera_status"


def test_legacy_names_are_kept_for_one_release():
    import shared.redis_keys as rk

    assert rk.LEGACY_WS_BROADCAST_CHANNEL == "nurby:ws:broadcast"
    assert rk.LEGACY_MQTT_BUS_CHANNEL == "nurby:mqtt:out"
    assert rk.LEGACY_RULES_INVALIDATE_CHANNEL == "nurby:rules:invalidate"
    assert rk.LEGACY_HEARTBEAT_PREFIX == "nurby:heartbeat:"
    assert rk.LEGACY_HEALTH_PREFIX == "nurby:health:"
    assert rk.LEGACY_CAMERA_STATUS_STREAM_KEY == "nurby:camera_status"


def test_relay_and_bridge_listen_on_both_channels(monkeypatch):
    monkeypatch.setenv("NURBY_INSTANCE_ID", "qa-1")
    import services.api.ws as ws
    import services.events.engine as engine
    import services.integrations.mqtt.bridge as bridge
    import shared.mqtt_bus as mqtt_bus

    # bridge rebinds the channel at import time from shared.mqtt_bus, so
    # the bus module must be reloaded first when another test imported it
    # under the default namespace.
    importlib.reload(mqtt_bus)
    importlib.reload(ws)
    importlib.reload(engine)
    importlib.reload(bridge)

    assert ws.WS_RELAY_CHANNEL == "qa-1:ws:broadcast"
    assert set(ws._RELAY_CHANNELS) == {"qa-1:ws:broadcast", "nurby:ws:broadcast"}
    assert engine.RULES_INVALIDATE_CHANNEL == "qa-1:rules:invalidate"
    assert set(engine._INVALIDATE_CHANNELS) == {"qa-1:rules:invalidate", "nurby:rules:invalidate"}
    assert bridge.MQTT_BUS_CHANNEL == "qa-1:mqtt:out"
    assert bridge.LEGACY_MQTT_BUS_CHANNEL == "nurby:mqtt:out"

    monkeypatch.delenv("NURBY_INSTANCE_ID")
    importlib.reload(ws)
    importlib.reload(engine)


def test_heartbeat_and_health_read_fallback(monkeypatch):
    monkeypatch.setenv("NURBY_INSTANCE_ID", "qa-1")
    import shared.component_health as ch
    import shared.heartbeat as hb

    importlib.reload(hb)
    importlib.reload(ch)
    assert hb._read_keys("ingestion") == ("qa-1:heartbeat:ingestion", "nurby:heartbeat:ingestion")
    assert ch._read_keys("vlm") == ("qa-1:health:vlm", "nurby:health:vlm")

    monkeypatch.delenv("NURBY_INSTANCE_ID")
    importlib.reload(hb)
    importlib.reload(ch)
    # Default namespace equals the legacy names, so single installs that
    # never set an instance id keep working unchanged.
    assert hb._read_keys("ingestion") == ("nurby:heartbeat:ingestion", "nurby:heartbeat:ingestion")


def test_per_camera_keys_are_deliberately_not_namespaced():
    """Keys that already embed a globally-unique id cannot collide between
    installs; namespacing them would churn contested call sites for no
    isolation gain."""
    import shared.redis_keys as rk

    assert rk.STREAM_RESTART_KEY_PREFIX == "nurby:stream_restart:"
