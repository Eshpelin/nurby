"""Broker configuration for the MQTT bridge.

Settings live in the app-settings key-value store (Settings -> MQTT in
the UI) so they are flippable without a redeploy. The password is stored
Fernet-sealed (sealed by the settings route) and unsealed here, with the
same tolerant fallback camera credentials use.
"""

import hashlib
import json
from dataclasses import dataclass

from shared.app_settings import DEFAULTS, get_setting
from shared.camera_secrets import unseal

# Settings that, when changed, should bounce the broker connection (or
# re-announce everything). The bridge compares fingerprints on a ticker;
# without this, editing the host would only apply after the next broker
# dropout.
_CONNECTION_KEYS = (
    "mqtt_host",
    "mqtt_port",
    "mqtt_username",
    "mqtt_password",
    "mqtt_tls",
    "mqtt_topic_prefix",
    "mqtt_client_id",
    "mqtt_enabled",
)
# Settings that only change what gets announced/published.
_BEHAVIOUR_KEYS = (
    "mqtt_discovery_enabled",
    "mqtt_stats_interval",
    "mqtt_camera_frame_interval",
)


@dataclass
class MqttConfig:
    enabled: bool = False
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    prefix: str = "nurby"
    client_id: str = "nurby"
    discovery_enabled: bool = True
    stats_interval: int = 60
    frame_interval: int = 10

    @property
    def connectable(self) -> bool:
        return bool(self.enabled and self.host)

    def fingerprint(self) -> str:
        """Hash of every setting that affects the connection or what is
        published. Pure, for tests."""
        raw = json.dumps(
            [
                self.host,
                self.port,
                self.username,
                self.password,
                self.tls,
                self.prefix,
                self.client_id,
                self.enabled,
                self.discovery_enabled,
                self.stats_interval,
                self.frame_interval,
            ],
            sort_keys=True,
        )
        return hashlib.md5(raw.encode()).hexdigest()


async def load_config() -> MqttConfig:
    """Read every mqtt_* setting. Defaults act as the floor."""
    cfg = MqttConfig(
        enabled=bool(await get_setting("mqtt_enabled", DEFAULTS["mqtt_enabled"])),
        host=str(await get_setting("mqtt_host", DEFAULTS["mqtt_host"]) or "").strip(),
        port=int(await get_setting("mqtt_port", DEFAULTS["mqtt_port"]) or 1883),
        username=str(await get_setting("mqtt_username", DEFAULTS["mqtt_username"]) or ""),
        password=unseal(str(await get_setting("mqtt_password", "") or "")) or "",
        tls=bool(await get_setting("mqtt_tls", DEFAULTS["mqtt_tls"])),
        prefix=str(await get_setting("mqtt_topic_prefix", DEFAULTS["mqtt_topic_prefix"]) or "nurby").strip("/") or "nurby",
        client_id=str(await get_setting("mqtt_client_id", DEFAULTS["mqtt_client_id"]) or "nurby"),
        discovery_enabled=bool(await get_setting("mqtt_discovery_enabled", DEFAULTS["mqtt_discovery_enabled"])),
        stats_interval=int(await get_setting("mqtt_stats_interval", DEFAULTS["mqtt_stats_interval"]) or 60),
        frame_interval=int(await get_setting("mqtt_camera_frame_interval", DEFAULTS["mqtt_camera_frame_interval"]) or 0),
    )
    return cfg


_cached_prefix: str | None = None
_cached_prefix_at: float = 0.0


async def current_prefix() -> str:
    """Cached topic-prefix read for per-frame producers (they must never
    hit the DB per publish, but a stale prefix for a minute is fine)."""
    global _cached_prefix, _cached_prefix_at
    import time

    now = time.monotonic()
    if _cached_prefix is None or now - _cached_prefix_at > 60:
        try:
            _cached_prefix = str(
                await get_setting("mqtt_topic_prefix", DEFAULTS["mqtt_topic_prefix"])
            ).strip("/") or "nurby"
        except Exception:
            _cached_prefix = "nurby"
        _cached_prefix_at = now
    return _cached_prefix
