"""Producer-side MQTT publishers (events, snapshots, motion).

Import-safe from every process (perception, ingestion): only shared
modules at import time — no aiomqtt, no DB engine. Everything is
fire-and-forget over the Redis bus; if the bridge is not running the
publishes are simply never drained.

Event payloads reuse the webhook payload shape (docs/webhooks.md) so
consumers get one vocabulary across Nurby's outbound surfaces, and the
per-camera event entity payload maps Nurby labels onto the HA event
entity's announced ``event_types`` (EVENT_TYPES here mirrors
discovery.EVENT_TYPES so the producer side stays dependency-light).
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from shared.mqtt_bus import mqtt_publish
from shared.mqtt_topics import (
    camera_events_topic,
    camera_motion_topic,
    camera_snapshot_topic,
    camera_slug,
    events_topic,
)
from services.integrations.mqtt.config import current_prefix

logger = logging.getLogger(__name__)

# HA event entity types. Anything not on this list is published as
# "object" because HA discards payloads whose event_type was not
# announced in the discovery config.
EVENT_TYPES = ("motion", "person", "face", "vehicle", "plate", "object")

_VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "bicycle", "boat", "train", "airplane"}
# Motion OFF hold, mirroring Frigate's mqtt_off_delay default.
MOTION_OFF_DELAY = 30.0

# slug cache fed by the ingestion manager on every sync (workers only
# know their camera id; slugs must match the bridge's derivation
# exactly, which camera_slug(name, id) guarantees without DB
# coordination).
_slugs: dict[str, str] = {}


def set_camera_slug(camera_id, slug: str) -> None:
    _slugs[str(camera_id)] = slug


def slug_for(camera_id) -> str | None:
    """Slug for a worker's camera id, as fed by the ingestion manager."""
    return _slugs.get(str(camera_id))


def prune_slugs(active_ids) -> None:
    active = {str(i) for i in active_ids}
    for key in list(_slugs):
        if key not in active:
            _slugs.pop(key, None)
            _motion_on.discard(key)
            _last_motion.pop(key, None)


def map_event_type(observation_data: dict) -> tuple[str, str | None, float | None]:
    """Map an observation onto (ha_event_type, raw_label, confidence)."""
    objects = (observation_data.get("object_detections") or {}).get("objects") or []
    if objects:
        first = objects[0] or {}
        label = first.get("label") or "object"
        confidence = first.get("confidence")
        if label == "person":
            return "person", label, confidence
        if label in _VEHICLE_LABELS:
            return "vehicle", label, confidence
        return "object", label, confidence
    faces = observation_data.get("person_detections") or {}
    if isinstance(faces, dict) and faces.get("count"):
        face = (faces.get("faces") or [{}])[0]
        return "face", "face", face.get("confidence")
    return "motion", None, None


async def publish_rule_event(event_id, rule, observation_data: dict, severity: str) -> None:
    """Fan one fired rule event out to MQTT. Called from firing.py right
    after the WS broadcast; never raises."""
    try:
        from services.events.actions import _build_default_payload, _build_template_context

        ctx = _build_template_context(observation_data, rule, event_id)
        payload = _build_default_payload(ctx)
        prefix = await current_prefix()

        await mqtt_publish(events_topic(prefix), json.dumps(payload, default=str))

        camera_id = str(observation_data.get("camera_id") or "")
        camera_name = str(observation_data.get("camera_name") or "")
        if not camera_id:
            return
        slug = camera_slug(camera_name, camera_id)
        event_type, label, confidence = map_event_type(observation_data)
        entity_payload = {
            "event_type": event_type,
            "event_id": str(event_id),
            "label": label,
            "confidence": confidence,
            "camera": camera_name,
            "severity": severity,
            "rule_name": rule.name,
            "timestamp": payload.get("timestamp"),
            "observation_id": payload.get("observation_id") or None,
            "recording_url": payload.get("recording_url") or None,
            "event_url": payload.get("event_url") or None,
        }
        await mqtt_publish(
            camera_events_topic(slug, prefix), json.dumps(entity_payload, default=str)
        )
        await publish_snapshot_from_path(
            slug, prefix, observation_data.get("thumbnail_path")
        )
    except Exception:
        logger.debug("mqtt event publish failed", exc_info=True)


async def publish_snapshot_from_path(slug: str, prefix: str, thumbnail_path) -> None:
    """Best-frame snapshot (raw JPEG bytes) for one observation.
    Thumbnail paths are stored cwd-relative (./thumbnails), shared by
    every service via the compose volume."""
    if not slug or not thumbnail_path:
        return
    try:
        path = Path(str(thumbnail_path))
        if not path.is_absolute():
            path = Path.cwd() / path
        jpeg = await asyncio.to_thread(path.read_bytes)
        await mqtt_publish(camera_snapshot_topic(slug, prefix), jpeg)
    except Exception:
        logger.debug("mqtt snapshot publish failed", exc_info=True)


# ── motion tracking (ingestion side) ─────────────────────────────────
#
# StreamWorkers see motion as continuous keyframes; the MQTT contract
# wants ON/OFF edges. State lives here (module-level, same process as
# the workers): ON on the first keyframe, OFF swept by the manager loop
# after MOTION_OFF_DELAY of quiet.

_motion_on: set[str] = set()
_last_motion: dict[str, float] = {}


async def note_motion(camera_id, slug: str) -> None:
    """Record keyframe activity; publish the ON edge on transition."""
    key = str(camera_id)
    _last_motion[key] = time.monotonic()
    if key in _motion_on or not slug:
        return
    _motion_on.add(key)
    await mqtt_publish(camera_motion_topic(slug), b"ON")


async def sweep_motion_off() -> None:
    """Publish OFF for cameras quiet for MOTION_OFF_DELAY. Called from
    the ingestion manager's periodic sync loop."""
    now = time.monotonic()
    for key in list(_motion_on):
        if now - _last_motion.get(key, 0.0) >= MOTION_OFF_DELAY:
            _motion_on.discard(key)
            slug = _slugs.get(key)
            if slug:
                await mqtt_publish(camera_motion_topic(slug), b"OFF")


# ── periodic live frames (ingestion side) ────────────────────────────
#
# HA's camera entity re-renders on every JPEG publish; a low-rate
# heartbeat keeps the tile roughly live without flooding the broker.
# The interval is read from app settings with a cache so the frame loop
# never blocks on the DB.

_frame_interval: int | None = None
_frame_interval_at = 0.0
_last_frame: dict[str, float] = {}


async def _frame_interval_seconds() -> int:
    global _frame_interval, _frame_interval_at
    now = time.monotonic()
    if _frame_interval is None or now - _frame_interval_at > 60:
        from shared.app_settings import get_setting

        try:
            raw = await get_setting("mqtt_camera_frame_interval", 10)
            _frame_interval = max(0, int(raw or 0))
        except Exception:
            _frame_interval = 10
        _frame_interval_at = now
    return int(_frame_interval or 0)


async def maybe_publish_frame(camera_id, frame_bgr, encode_jpeg) -> None:
    """Rate-limited periodic JPEG publish. ``encode_jpeg`` is the
    caller's encoder (a cv2.imencode wrapper) so this module stays free
    of OpenCV. Skips everything when the interval is 0."""
    try:
        interval = await _frame_interval_seconds()
        if interval <= 0:
            return
        key = str(camera_id)
        now = time.monotonic()
        if now - _last_frame.get(key, 0.0) < interval:
            return
        slug = _slugs.get(key)
        if not slug:
            return
        _last_frame[key] = now
        jpeg = await asyncio.to_thread(encode_jpeg, frame_bgr)
        if jpeg:
            await mqtt_publish(camera_snapshot_topic(slug), jpeg)
    except Exception:
        logger.debug("mqtt frame publish failed", exc_info=True)
