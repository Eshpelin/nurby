"""Inbound MQTT command handling for camera toggles.

HA switches publish ``ON``/``OFF`` to ``{prefix}/cameras/{slug}/<toggle>/set``.
The bridge resolves the slug against its current camera inventory, writes
the underlying Camera column, then mirrors the new state on the retained
``/state`` topic for instant HA feedback. Recording and enable changes
additionally set the stream-restart key so the ingestion manager acts
immediately instead of waiting out its poll interval (``detect`` flows
through perception's 30s camera-config cache — no restart needed, and
restarting the stream for it would drop frames for nothing).
"""

import logging
import uuid

from shared.database import async_session
from shared.models import Camera
from shared.mqtt_bus import bus_redis, mqtt_publish
from shared.mqtt_topics import camera_state_topic
from shared.redis_keys import STREAM_RESTART_KEY_PREFIX

logger = logging.getLogger(__name__)

_ON = {"on", "1", "true", "yes"}
_OFF = {"off", "0", "false", "no"}


def parse_toggle_payload(payload: bytes | str) -> bool | None:
    """ON/OFF (HA default), plus 1/0 and true/false. None = unparsable."""
    value = (payload.decode() if isinstance(payload, bytes) else payload).strip().lower()
    if value in _ON:
        return True
    if value in _OFF:
        return False
    return None


def _new_state(camera: Camera, toggle: str) -> bool:
    if toggle == "detect":
        return bool(camera.detect_objects)
    if toggle == "recordings":
        return (camera.recording_mode or "always") != "off"
    return bool(camera.enabled)


async def handle_command(
    camera_id: uuid.UUID,
    slug: str,
    toggle: str,
    payload: bytes,
    prefix: str,
) -> tuple[bool | None, str]:
    """Apply one camera toggle. Returns (new_state, error) — state None
    means the command was not applicable (unknown camera / payload)."""
    on = parse_toggle_payload(payload)
    if on is None:
        return None, f"unparsable payload {payload[:16]!r}; expected ON or OFF"

    restart_stream = False
    async with async_session() as db:
        camera = await db.get(Camera, camera_id)
        if camera is None:
            return None, "unknown camera"
        if toggle == "detect":
            camera.detect_objects = on
        elif toggle == "recordings":
            # Boolean switch over the richer per-camera mode: OFF wins
            # outright; ON resumes continuous recording.
            camera.recording_mode = "always" if on else "off"
            restart_stream = True
        elif toggle == "enabled":
            camera.enabled = on
            restart_stream = True
        else:  # guarded by TOGGLEABLE, defensive only
            return None, f"unsupported toggle {toggle!r}"
        new_state = _new_state(camera, toggle)
        await db.commit()

    if restart_stream:
        try:
            r = await bus_redis()
            await r.set(f"{STREAM_RESTART_KEY_PREFIX}{camera_id}", "1")
        except Exception:
            logger.debug("stream restart signal failed", exc_info=True)

    await mqtt_publish(
        camera_state_topic(slug, toggle, prefix),
        b"ON" if new_state else b"OFF",
        retain=True,
    )
    return new_state, ""
