"""Redis stream / key / channel names shared across services.

Kept here so a consumer (e.g. the perception camera-status watcher) can name
the stream without importing a producer module like
``services.ingestion.stream`` and dragging in its heavy deps (OpenCV, the
video writer). The perception image does not even ship ``services/ingestion``,
so that import crash-loops the process.

Per-install namespacing (#291). Redis pub/sub channels are NOT scoped by
the database index, and shared-key collisions only stay harmless while
every name embeds a per-install unique id. Two Nurby stacks pointing at
the same Redis server — a QA stack beside prod, two checkouts on one dev
box, which is exactly what the default compose file encourages — used to
relay each other's live alerts into each other's dashboards, cross-drain
each other's heartbeat keys, and read each other's camera-status stream.
Every instance-shared name is therefore built here and prefixed with the
install namespace: ``NURBY_INSTANCE_ID`` env, else the compose project
name, else ``nurby``.

One-release rolling-update compatibility: the WS relay and the MQTT
bridge subscribe to both the namespaced and the legacy channel, so
processes from the previous release (still publishing on ``nurby:...``)
are heard until the whole stack has restarted. Heartbeat and health
readers fall back to the legacy key when the namespaced one is absent
for the same reason. Remove the ``LEGACY_*`` names in a future release.

Deliberately NOT namespaced: keys that already embed a globally-unique id
(per-camera UUIDs such as ``nurby:stream_restart:<uuid>`` and cooldown
keys keyed by rule UUID) cannot collide between installs.
"""

import os
import re

# Camera availability edges (offline / back online) for the rule engine.
# A stream rather than pubsub so a transition that happens while the
# perception process is restarting is delivered when it comes back, not
# lost. Tamper alerting cannot ride a fire-and-forget channel.
CAMERA_STATUS_STREAM_MAXLEN = 500

# Per-camera stream-restart signal. Set (existence-check key) by the
# camera PATCH route and the MQTT bridge command handlers; the ingestion
# manager's sync loop consumes and deletes it to rebuild the worker
# immediately instead of waiting for the next config-diff pass.
STREAM_RESTART_KEY_PREFIX = "nurby:stream_restart:"


def instance_namespace() -> str:
    """Stable per-install fragment for every shared Redis name."""
    raw = (
        os.environ.get("NURBY_INSTANCE_ID")
        or os.environ.get("COMPOSE_PROJECT_NAME")
        or "nurby"
    ).strip()
    # Keep it a safe key/channel fragment even with odd project names.
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", raw)
    return safe or "nurby"


def namespaced(name: str) -> str:
    return f"{instance_namespace()}:{name}"


# ── Instance-shared names (all built through namespaced()) ──

def camera_status_stream_key() -> str:
    return namespaced("camera_status")


def ws_broadcast_channel() -> str:
    return namespaced("ws:broadcast")


def mqtt_bus_channel() -> str:
    return namespaced("mqtt:out")


def rules_invalidate_channel() -> str:
    return namespaced("rules:invalidate")


def heartbeat_key(service: str) -> str:
    return namespaced(f"heartbeat:{service}")


def health_key(component: str) -> str:
    return namespaced(f"health:{component}")


# Import-time constants for the producers/consumers that import a name
# rather than call a builder. The namespace comes from the process
# environment, which is fixed for the life of the process, so evaluating
# once at import is equivalent to calling the builder each time.
CAMERA_STATUS_STREAM_KEY = camera_status_stream_key()


# ── Legacy names (pre-#291). Readers only; kept for one release. ──

LEGACY_WS_BROADCAST_CHANNEL = "nurby:ws:broadcast"
LEGACY_MQTT_BUS_CHANNEL = "nurby:mqtt:out"
LEGACY_RULES_INVALIDATE_CHANNEL = "nurby:rules:invalidate"
LEGACY_HEARTBEAT_PREFIX = "nurby:heartbeat:"
LEGACY_HEALTH_PREFIX = "nurby:health:"
LEGACY_CAMERA_STATUS_STREAM_KEY = "nurby:camera_status"
