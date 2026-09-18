"""MQTT topic contract and slug helpers shared across processes.

Pure string builders — no imports beyond the stdlib — so the ingestion,
perception and API processes all derive identical topics without
coordinating through the database. The topic tree mirrors Frigate's
conventions (see docs/integrations/mqtt.md):

    {prefix}/status                              birth / will (retained)
    {prefix}/stats
    {prefix}/events
    {prefix}/cameras/{slug}/motion
    {prefix}/cameras/{slug}/events
    {prefix}/cameras/{slug}/snapshot
    {prefix}/cameras/{slug}/detect/set | /state
    {prefix}/cameras/{slug}/recordings/set | /state
    {prefix}/cameras/{slug}/enabled/set | /state

The slug is the camera name slugified with a short uuid suffix so it is
readable like Frigate's camera topics yet collision-free and derivable
from (name, id) alone. It changes on rename — Home Assistant entities
keep their identity through the camera-UUID-derived unique_ids instead.
"""

import re
import uuid

DEFAULT_PREFIX = "nurby"
STATUS = "status"
STATS = "stats"
EVENTS = "events"
CAMERAS = "cameras"

# Commands the bridge accepts on {prefix}/cameras/{slug}/<name>/set.
# State mirrors live on the sibling /state topic (retained).
TOGGLEABLE = ("detect", "recordings", "enabled")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def camera_slug(name: str, camera_id: uuid.UUID | str) -> str:
    """Stable readable topic segment for a camera.

    "Front Door" + uuid 3f2a… -> "front-door-3f2a". The 4-char suffix
    keeps same-named cameras apart without a shared lookup; collisions
    need an identical name AND identical 4 hex chars.
    """
    base = _SLUG_RE.sub("-", (name or "").lower()).strip("-")[:48]
    suffix = str(camera_id).replace("-", "")[:4]
    return f"{base or 'camera'}-{suffix}"


def status_topic(prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{STATUS}"


def stats_topic(prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{STATS}"


def events_topic(prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{EVENTS}"


def camera_motion_topic(slug: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{CAMERAS}/{slug}/motion"


def camera_events_topic(slug: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{CAMERAS}/{slug}/{EVENTS}"


def camera_snapshot_topic(slug: str, prefix: str = DEFAULT_PREFIX) -> str:
    return f"{prefix}/{CAMERAS}/{slug}/snapshot"


def camera_state_topic(slug: str, name: str, prefix: str = DEFAULT_PREFIX) -> str:
    """Retained state mirror for one of TOGGLEABLE, e.g. .../detect/state."""
    _check_toggle(name)
    return f"{prefix}/{CAMERAS}/{slug}/{name}/state"


def camera_command_topic(slug: str, name: str, prefix: str = DEFAULT_PREFIX) -> str:
    """Command topic for one of TOGGLEABLE, e.g. .../detect/set."""
    _check_toggle(name)
    return f"{prefix}/{CAMERAS}/{slug}/{name}/set"


def parse_camera_command(topic: str, prefix: str) -> tuple[str, str] | None:
    """Match ``{prefix}/cameras/{slug}/{name}/set``.

    Returns (slug, toggle_name) or None for anything else — including
    our own /state publishes, which must not loop back through the
    handler (Frigate's echo-filter problem).
    """
    cam_prefix = f"{prefix}/{CAMERAS}/"
    if not topic.startswith(cam_prefix) or not topic.endswith("/set"):
        return None
    parts = topic[len(cam_prefix) : -len("/set")].split("/")
    if len(parts) != 2:
        return None
    slug, name = parts
    if name not in TOGGLEABLE:
        return None
    return slug, name


def _check_toggle(name: str) -> None:
    if name not in TOGGLEABLE:
        raise ValueError(f"unknown camera toggle {name!r}; expected one of {TOGGLEABLE}")
