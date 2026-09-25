"""Cross-process MQTT publish bus.

The MQTT broker connection lives in one place (the API process's
bridge, mirroring the Telegram poller supervisor), but events fire and
frames flow in the perception and ingestion processes. Producers
publish onto a Redis pub/sub channel; the bridge drains it and forwards
to the broker. This is the same decoupling the WebSocket relay uses
(``nurby:ws:broadcast``).

Fire-and-forget by design: Redis being down must never break a rule
firing or a frame loop, and with no bridge running the publishes are
near-free. Telemetry that lands while the broker is reconnecting is
lost, except retained messages, which the bridge buffers per topic.
"""

import base64
import json
import logging

from shared.config import settings
from shared.redis_keys import LEGACY_MQTT_BUS_CHANNEL, mqtt_bus_channel

logger = logging.getLogger(__name__)

# Namespaced per install (#291): the bus is a consumed queue in spirit —
# two stacks sharing Redis would split each other's MQTT publishes between
# their bridges. The bridge also listens on the legacy channel for one
# release so pre-update producers are heard. Remove the LEGACY name in a
# future release.
MQTT_BUS_CHANNEL = mqtt_bus_channel()

_redis = None


def bus_redis():
    """Shared bus redis connection. Public so the bridge command
    handlers can reuse it for non-bus signals (stream restarts)."""
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def mqtt_publish(topic: str, payload: str | bytes, retain: bool = False) -> None:
    """Queue one MQTT message for the bridge. Never raises.

    String payloads ride as-is; bytes (JPEG snapshots) are base64-wrapped
    so the whole envelope stays JSON on the wire.
    """
    env: dict[str, object] = {"t": topic, "r": retain}
    if isinstance(payload, bytes):
        env["b"] = base64.b64encode(payload).decode("ascii")
    else:
        env["s"] = payload
    try:
        await bus_redis().publish(MQTT_BUS_CHANNEL, json.dumps(env))
    except Exception:
        logger.debug("mqtt bus publish failed for %s", topic, exc_info=True)


def decode_bus_message(raw: str | bytes) -> tuple[str, bytes, bool] | None:
    """Decode one bus envelope into (topic, payload_bytes, retain).

    Pure, for tests. Returns None on malformed envelopes so the bridge
    can skip them.
    """
    try:
        env = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(env, dict) or not isinstance(env.get("t"), str):
        return None
    if "s" in env:
        payload = str(env["s"]).encode("utf-8")
    elif "b" in env:
        try:
            payload = base64.b64decode(env["b"])
        except (ValueError, TypeError):
            return None
    else:
        return None
    return env["t"], payload, bool(env.get("r"))
