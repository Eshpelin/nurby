"""Home Assistant MQTT discovery payload builders (pure functions).

Publishes retained configs under ``homeassistant/<component>/<object_id>/config``
so Home Assistant builds entities with zero YAML. Structure:

- one hub device (``identifiers: ["nurby"]``) carrying the stats sensor —
  the hub must exist before children reference it via ``via_device``;
- one device per camera (``identifiers: ["nurby_{camera_id}"]``) with
  motion binary_sensor, detections event entity, snapshot camera entity,
  and detect/recordings/enabled switches;
- every entity binds ``availability_topic`` to ``{prefix}/status``.

``unique_id``s derive from the stable camera UUID so entity identity
survives renames (the name-slug topic moves; discovery is republished).

Removal is the HA convention: publish an empty payload to the config
topic and the entity is deleted.
"""

from typing import Any

from shared.mqtt_topics import (
    camera_command_topic,
    camera_events_topic,
    camera_motion_topic,
    camera_snapshot_topic,
    camera_slug,
    camera_state_topic,
    stats_topic,
    status_topic,
)

# Home Assistant `event` entity types Nurby can emit. The event
# publisher maps every Nurby label onto one of these (anything unknown
# becomes "object") because HA discards payloads whose event_type is
# not in the announced list.
EVENT_TYPES = ["motion", "person", "face", "vehicle", "plate", "object"]

SWITCHES = ("detect", "recordings", "enabled")

_SW_VERSION: str | None = None


def _sw_version() -> str:
    global _SW_VERSION
    if _SW_VERSION is None:
        try:
            from shared.version import current_version

            _SW_VERSION = current_version()
        except Exception:
            _SW_VERSION = "dev"
    return _SW_VERSION


def _availability(prefix: str) -> dict[str, str]:
    return {
        "availability_topic": status_topic(prefix),
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _hub_device() -> dict[str, Any]:
    return {
        "identifiers": ["nurby"],
        "name": "Nurby",
        "manufacturer": "Nurby",
        "model": "Self-hosted AI NVR",
        "sw_version": _sw_version(),
    }


def _camera_device(camera) -> dict[str, Any]:
    return {
        "identifiers": [f"nurby_{camera.id}"],
        "name": camera.name,
        "manufacturer": "Nurby",
        "model": "Camera",
        "via_device": "nurby",
    }


def _config_topic(component: str, unique_id: str) -> str:
    # Best practice per HA docs: object_id == unique_id, no node_id.
    return f"homeassistant/{component}/{unique_id}/config"


def stats_sensor_config(prefix: str) -> tuple[str, dict[str, Any]]:
    """Hub-device sensor: cameras online count, full stats as attributes."""
    unique_id = "nurby_stats"
    payload = {
        "name": "Cameras online",
        "unique_id": unique_id,
        "state_topic": stats_topic(prefix),
        "value_template": "{{ value_json.cameras_online }}",
        "json_attributes_topic": stats_topic(prefix),
        **_availability(prefix),
        "device": _hub_device(),
    }
    return _config_topic("sensor", unique_id), payload


def camera_configs(camera, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    """All discovery messages for one camera, keyed by config topic.
    ``camera`` is a raw Camera row; the slug derives from (name, id)."""
    slug = camera_slug(camera.name, camera.id)
    cid = str(camera.id)
    base_avail = _availability(prefix)

    motion = {
        "name": "Motion",
        "unique_id": f"nurby_{cid}_motion",
        "state_topic": camera_motion_topic(slug, prefix),
        "device_class": "motion",
        "payload_on": "ON",
        "payload_off": "OFF",
        **base_avail,
        "device": _camera_device(camera),
    }
    detections = {
        "name": "Detections",
        "unique_id": f"nurby_{cid}_events",
        "state_topic": camera_events_topic(slug, prefix),
        "event_types": EVENT_TYPES,
        **base_avail,
        "device": _camera_device(camera),
    }
    snapshot = {
        "name": "Snapshots",
        "unique_id": f"nurby_{cid}_camera",
        "topic": camera_snapshot_topic(slug, prefix),
        **base_avail,
        "device": _camera_device(camera),
    }
    out = [
        (_config_topic("binary_sensor", f"nurby_{cid}_motion"), motion),
        (_config_topic("event", f"nurby_{cid}_events"), detections),
        (_config_topic("camera", f"nurby_{cid}_camera"), snapshot),
    ]
    for toggle in SWITCHES:
        human = toggle.capitalize()
        out.append(
            (
                _config_topic("switch", f"nurby_{cid}_{toggle}"),
                {
                    "name": human,
                    "unique_id": f"nurby_{cid}_{toggle}",
                    "state_topic": camera_state_topic(slug, toggle, prefix),
                    "command_topic": camera_command_topic(slug, toggle, prefix),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "state_on": "ON",
                    "state_off": "OFF",
                    **base_avail,
                    "device": _camera_device(camera),
                },
            )
        )
    return out


def camera_removal_topics(camera) -> list[str]:
    """Config topics to blank out when a camera disappears."""
    cid = str(camera.id)
    topics = [
        _config_topic("binary_sensor", f"nurby_{cid}_motion"),
        _config_topic("event", f"nurby_{cid}_events"),
        _config_topic("camera", f"nurby_{cid}_camera"),
    ]
    topics.extend(_config_topic("switch", f"nurby_{cid}_{t}") for t in SWITCHES)
    return topics


def all_removal_topics() -> list[str]:
    """Every discovery topic Nurby could have announced, for integration
    teardown when discovery is switched off."""
    return [_config_topic("sensor", "nurby_stats")]
