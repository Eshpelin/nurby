"""Tests for HA discovery payload builders (services/integrations/mqtt/discovery.py)."""

import json
import uuid
from types import SimpleNamespace

from services.integrations.mqtt import discovery

CID = uuid.uuid4()


def make_camera(**over):
    cam = SimpleNamespace(
        id=CID, name="Front Door", enabled=True, detect_objects=True,
        recording_mode="always", status="live", display_order=0,
    )
    for k, v in over.items():
        setattr(cam, k, v)
    return cam


def test_camera_configs_cover_all_components():
    msgs = dict(discovery.camera_configs(make_camera(), "nurby"))
    components = sorted(t.split("/")[1] for t in msgs)
    assert components == ["binary_sensor", "camera", "event", "switch", "switch", "switch"]
    # One config per entity, object_id == unique_id (HA best practice,
    # no node_id level).
    for topic, payload in msgs.items():
        parts = topic.split("/")
        assert topic.startswith("homeassistant/")
        assert parts[1] in {"binary_sensor", "camera", "event", "switch"}
        assert parts[2] == payload["unique_id"]
        assert parts[3] == "config"


def test_unique_ids_derive_from_camera_uuid_not_name():
    a = dict(discovery.camera_configs(make_camera(name="Porch"), "nurby"))
    b = dict(discovery.camera_configs(make_camera(name="Driveway"), "nurby"))
    a_ids = {p["unique_id"] for p in a.values()}
    b_ids = {p["unique_id"] for p in b.values()}
    assert a_ids == b_ids, "renames must keep entity identity via uuid unique_ids"
    # ...while the state topics move with the name slug.
    a_topics = {p["state_topic"] for p in a.values() if "state_topic" in p}
    assert any("porch-" in t for t in a_topics)


def test_every_entity_binds_hub_availability():
    for _, payload in discovery.camera_configs(make_camera(), "nurby") + [
        discovery.stats_sensor_config("nurby")
    ]:
        assert payload["availability_topic"] == "nurby/status"
        assert payload["payload_available"] == "online"
        assert payload["payload_not_available"] == "offline"


def test_camera_devices_nest_under_hub_via_via_device():
    _, stats = discovery.stats_sensor_config("nurby")
    assert stats["device"]["identifiers"] == ["nurby"]
    assert "via_device" not in stats["device"]  # the hub itself
    msgs = discovery.camera_configs(make_camera(), "nurby")
    for _, payload in msgs:
        dev = payload["device"]
        assert dev["identifiers"] == [f"nurby_{CID}"]
        assert dev["via_device"] == "nurby"


def test_switches_bind_state_and_command_topics():
    msgs = dict(discovery.camera_configs(make_camera(), "nurby"))
    switches = {p["name"]: p for t, p in msgs.items() if "/switch/" in t}
    assert set(switches) == {"Detect", "Recordings", "Enabled"}
    for p in switches.values():
        assert p["command_topic"].endswith("/set")
        assert p["state_topic"].endswith("/state")
        assert p["state_topic"] != p["command_topic"]


def test_event_entity_announces_supported_event_types():
    msgs = dict(discovery.camera_configs(make_camera(), "nurby"))
    event = next(p for t, p in msgs.items() if "/event/" in t)
    assert set(discovery.EVENT_TYPES) <= set(event["event_types"])
    # Payloads must stay JSON-serializable for the bridge.
    for _, payload in msgs.items():
        json.dumps(payload)


def test_motion_sensor_is_a_motion_class_binary_sensor():
    msgs = dict(discovery.camera_configs(make_camera(), "nurby"))
    motion = next(p for t, p in msgs.items() if "/binary_sensor/" in t)
    assert motion["device_class"] == "motion"
    assert motion["payload_on"] == "ON" and motion["payload_off"] == "OFF"
    assert motion["state_topic"] == f"nurby/cameras/{discovery.camera_slug('Front Door', CID)}/motion"


def test_removal_topics_cover_every_config_topic():
    cam = make_camera()
    configs = {t for t, _ in discovery.camera_configs(cam, "nurby")}
    removals = set(discovery.camera_removal_topics(cam))
    assert removals == configs
    assert "homeassistant/sensor/nurby_stats/config" in discovery.all_removal_topics()


def test_custom_prefix_flows_through_every_topic():
    msgs = discovery.camera_configs(make_camera(), "campus")
    for topic, payload in msgs:
        blob = json.dumps(payload)
        assert "campus/" in blob
        assert "nurby/cameras" not in blob
