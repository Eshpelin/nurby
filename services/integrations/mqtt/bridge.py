"""The MQTT bridge: one broker connection for the whole Nurby install.

Runs as a supervisor asyncio task in the API process (same lifecycle as
the Telegram poller manager): started in the lifespan, reconciled
against app settings every few seconds, exponential backoff on broker
errors. Design notes in docs/integrations/mqtt.md; the mechanics follow
Frigate's comms layer:

- birth on connect / Last Will on ungraceful loss / "stopped" on clean
  shutdown, all retained on ``{prefix}/status``;
- subscribes its own tree plus ``homeassistant/status``; retained
  inbound messages are skipped (they are echoes of our own state
  publishes) and everything else under the prefix that is not a command
  is ignored;
- retained publishes are buffered per topic and replayed after a
  reconnect so state survives broker outages;
- a reconcile ticker re-reads settings and the camera table, republishes
  discovery/state on change, and bounces the connection when
  connection-affecting settings change.
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid

import aiomqtt
from sqlalchemy import select

from shared.database import async_session
from shared.models import Camera
from shared.mqtt_bus import MQTT_BUS_CHANNEL, bus_redis, decode_bus_message
from shared.mqtt_topics import (
    camera_slug,
    camera_state_topic,
    parse_camera_command,
    stats_topic,
    status_topic,
)
from services.integrations.mqtt import discovery, handlers
from services.integrations.mqtt.config import MqttConfig, load_config

logger = logging.getLogger(__name__)

HA_STATUS_TOPIC = "homeassistant/status"
_RECONNECT_BACKOFF_MAX = 60.0
_SETTINGS_TICK = 15.0


class MqttBridge:
    """Singleton supervisor. Producers elsewhere never touch this — they
    publish through the Redis bus."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.last_error: str | None = None
        self.last_connected_at: float | None = None
        self.announced_entities = 0
        # slug -> camera id, refreshed by the reconcile pass; the command
        # path resolves inbound /set topics against it.
        self._slugs: dict[str, str] = {}
        # Retained publishes buffered for replay after reconnect (last
        # value per topic wins, mirroring Frigate's _pending_retained).
        self._retained: dict[str, bytes] = {}
        # Discovery config topics currently announced to the broker, so
        # teardown can blank them and updates only republish changes.
        self._announced: set[str] = set()
        self._inventory_fingerprint: str | None = None

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self.run(), name="mqtt-bridge")

    def stop(self) -> None:
        self._stop.set()

    def cancel(self) -> None:
        """Shutdown path: request stop and cancel the task. The run loop
        publishes "stopped" and disconnects cleanly when it wins the race;
        cancellation covers a wedged session."""
        self.stop()
        if self._task is not None:
            self._task.cancel()

    async def run(self) -> None:
        """Supervisor loop: load config, hold a session, backoff on errors."""
        delay = 1.0
        while not self._stop.is_set():
            cfg = await load_config()
            if not cfg.connectable:
                self.connected = False
                await self._sleep_or_stop(10.0)
                continue
            try:
                await self._session(cfg)
                delay = 1.0
                if self._stop.is_set():
                    break
            except BaseException as exc:  # noqa: BLE001 - supervisor must survive anything
                if isinstance(exc, asyncio.CancelledError):
                    raise
                self._classify_session_error(exc)
            self.connected = False
            if self._stop.is_set():
                break
            await self._sleep_or_stop(delay)
            delay = min(delay * 2, _RECONNECT_BACKOFF_MAX)

    def _classify_session_error(self, exc: BaseException) -> None:
        """Log + record a session error. CancelledError always propagates."""
        errors = exc.exceptions if isinstance(exc, ExceptionGroup) else [exc]
        if any(isinstance(e, asyncio.CancelledError) for e in errors):
            raise exc
        mqtt_errors = [e for e in errors if isinstance(e, aiomqtt.MqttError)]
        if mqtt_errors and len(mqtt_errors) == len(errors):
            self.last_error = str(mqtt_errors[0]) or type(mqtt_errors[0]).__name__
            logger.warning("MQTT broker error, reconnecting: %s", self.last_error)
        else:
            self.last_error = "unexpected bridge error (see logs)"
            logger.exception("MQTT bridge session failed", exc_info=exc)

    async def _sleep_or_stop(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)

    # ── one connection ───────────────────────────────────────────────
    async def _session(self, cfg: MqttConfig) -> None:
        will = aiomqtt.WillMessage(
            topic=status_topic(cfg.prefix), payload=b"offline", qos=1, retain=True
        )
        client = aiomqtt.Client(
            hostname=cfg.host,
            port=cfg.port,
            identifier=cfg.client_id,
            username=cfg.username or None,
            password=cfg.password or None,
            will=will,
            tls_params=aiomqtt.TLSParameters() if cfg.tls else None,
            timeout=10.0,
        )
        session_stop = asyncio.Event()
        async with client:
            await client.subscribe(f"{cfg.prefix}/#", qos=1)
            await client.subscribe(HA_STATUS_TOPIC, qos=1)
            self.connected = True
            self.last_connected_at = time.time()
            logger.info("MQTT connected to %s:%s as %s", cfg.host, cfg.port, cfg.client_id)
            # Birth, replay of state buffered while offline, full announce.
            await self._publish(client, status_topic(cfg.prefix), b"online", retain=True)
            for topic, payload in list(self._retained.items()):
                await self._publish(client, topic, payload, retain=True)
            await self._announce(client, cfg, force=True)
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._message_loop(client, cfg, session_stop))
                    tg.create_task(self._bus_loop(client, cfg, session_stop))
                    tg.create_task(self._stats_loop(client, cfg, session_stop))
                    tg.create_task(self._reconcile_loop(client, cfg, session_stop))
                    tg.create_task(self._wait_global_stop(session_stop))
            finally:
                self.connected = False
                if self._stop.is_set():
                    # Graceful shutdown: publish "stopped" before the clean
                    # disconnect (which suppresses the will), like Frigate.
                    with contextlib.suppress(Exception):
                        await client.publish(
                            status_topic(cfg.prefix), payload=b"stopped", qos=1, retain=True
                        )

    async def _wait_global_stop(self, session_stop: asyncio.Event) -> None:
        await self._stop.wait()
        session_stop.set()

    # ── publish helper ───────────────────────────────────────────────
    async def _publish(
        self,
        client: aiomqtt.Client,
        topic: str,
        payload: bytes | str,
        retain: bool = False,
    ) -> None:
        await client.publish(topic, payload=payload, qos=1, retain=retain)
        if retain:
            self._retained[topic] = payload.encode() if isinstance(payload, str) else payload

    # ── inbound messages ─────────────────────────────────────────────
    async def _message_loop(
        self, client: aiomqtt.Client, cfg: MqttConfig, stop: asyncio.Event
    ) -> None:
        async for message in client.messages:
            if stop.is_set():
                return
            topic = str(message.topic)
            payload = (
                message.payload if isinstance(message.payload, bytes) else str(message.payload).encode()
            )
            if topic == HA_STATUS_TOPIC:
                # Home Assistant just (re)started — re-announce so its
                # entities are rebuilt without waiting for a Nurby change.
                if payload == b"online":
                    await self._announce(client, cfg, force=True)
                continue
            if message.retain:
                # Broker replay of our own retained publishes (echo).
                continue
            cmd = parse_camera_command(topic, cfg.prefix)
            if cmd is None:
                continue
            slug, toggle = cmd
            camera_id = self._slugs.get(slug)
            if camera_id is None:
                logger.debug("MQTT command for unknown camera slug %r", slug)
                continue
            state, error = await handlers.handle_command(
                uuid.UUID(camera_id), slug, toggle, payload, cfg.prefix
            )
            if error:
                logger.warning("MQTT command %s rejected: %s", topic, error)

    # ── bus drain ────────────────────────────────────────────────────
    async def _bus_loop(
        self, client: aiomqtt.Client, cfg: MqttConfig, stop: asyncio.Event
    ) -> None:
        ps = bus_redis().pubsub()
        await ps.subscribe(MQTT_BUS_CHANNEL)
        try:
            while not stop.is_set():
                msg = await ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not msg or not msg.get("data"):
                    continue
                decoded = decode_bus_message(msg["data"])
                if decoded is None:
                    continue
                topic, payload, retain = decoded
                await self._publish(client, topic, payload, retain=retain)
        finally:
            with contextlib.suppress(Exception):
                await ps.aclose()

    # ── tickers ──────────────────────────────────────────────────────
    async def _stats_loop(
        self, client: aiomqtt.Client, cfg: MqttConfig, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            await self._sleep(stop, max(5, cfg.stats_interval))
            if stop.is_set():
                return
            try:
                stats = await collect_stats()
            except Exception:
                logger.exception("stats collection failed")
                continue
            await self._publish(
                client, stats_topic(cfg.prefix), json.dumps(stats, default=str), retain=False
            )

    async def _reconcile_loop(
        self, client: aiomqtt.Client, cfg: MqttConfig, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            await self._sleep(stop, _SETTINGS_TICK)
            if stop.is_set():
                return
            fresh = await load_config()
            if fresh.fingerprint() != cfg.fingerprint():
                # Connection- or behaviour-affecting change: drop the
                # session; run() reconnects with the new config.
                stop.set()
                return
            if await self._inventory_changed(fresh):
                await self._announce(client, fresh, force=False)

    async def _sleep(self, stop: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)

    # ── announce / reconcile ─────────────────────────────────────────
    @staticmethod
    def _camera_fingerprint(cameras: list[Camera], cfg: MqttConfig) -> str:
        raw = json.dumps(
            {
                "discovery": cfg.discovery_enabled,
                "prefix": cfg.prefix,
                "cams": sorted(
                    (
                        str(c.id),
                        c.name,
                        bool(c.enabled),
                        bool(c.detect_objects),
                        (c.recording_mode or "always") != "off",
                    )
                    for c in cameras
                ),
            },
            sort_keys=True,
        )
        return raw

    async def _inventory_changed(self, cfg: MqttConfig) -> bool:
        cameras = await _load_cameras()
        return self._camera_fingerprint(cameras, cfg) != self._inventory_fingerprint

    async def _announce(self, client: aiomqtt.Client, cfg: MqttConfig, force: bool) -> None:
        """Publish discovery configs (retained) + camera state mirrors."""
        cameras = await _load_cameras()
        self._inventory_fingerprint = self._camera_fingerprint(cameras, cfg)
        self._slugs = {camera_slug(c.name, c.id): str(c.id) for c in cameras}

        wanted: set[str] = set()
        if cfg.discovery_enabled:
            messages: list[tuple[str, dict]] = [discovery.stats_sensor_config(cfg.prefix)]
            for cam in cameras:
                messages.extend(discovery.camera_configs(cam, cfg.prefix))
            wanted = {topic for topic, _ in messages}
            # Teardown for cameras that disappeared or were renamed.
            for stale in sorted(self._announced - wanted):
                with contextlib.suppress(Exception):
                    await self._publish(client, stale, b"", retain=True)
            for topic, payload in messages:
                if force or topic not in self._announced:
                    body = json.dumps(payload, separators=(",", ":"))
                    await self._publish(client, topic, body, retain=True)
            self._announced = wanted
        elif self._announced:
            for topic in sorted(self._announced):
                with contextlib.suppress(Exception):
                    await self._publish(client, topic, b"", retain=True)
            self._announced.clear()

        # Retained state mirrors so HA switches show the truth immediately.
        for cam in cameras:
            slug = camera_slug(cam.name, cam.id)
            for toggle, on in (
                ("detect", bool(cam.detect_objects)),
                ("recordings", (cam.recording_mode or "always") != "off"),
                ("enabled", bool(cam.enabled)),
            ):
                await self._publish(
                    client,
                    camera_state_topic(slug, toggle, cfg.prefix),
                    b"ON" if on else b"OFF",
                    retain=True,
                )
        self.announced_entities = len(self._announced)


async def _load_cameras() -> list[Camera]:
    async with async_session() as db:
        result = await db.execute(select(Camera).order_by(Camera.display_order, Camera.name))
        return list(result.scalars().all())


async def collect_stats() -> dict:
    """Stats snapshot published on {prefix}/stats. Same vocabulary the
    dashboard status endpoint reports, so consumers get one vocabulary."""
    async with async_session() as db:
        cameras = (await db.execute(select(Camera))).scalars().all()
    online = sum(1 for c in cameras if (c.status or "offline") != "offline")
    recording = sum(1 for c in cameras if c.status == "recording")
    try:
        from services.api.main import START_TIME

        uptime: float | None = time.time() - START_TIME
    except Exception:
        uptime = None
    return {
        "cameras_total": len(cameras),
        "cameras_online": online,
        "cameras_recording": recording,
        "uptime_seconds": round(uptime, 1) if uptime is not None else None,
        "timestamp": time.time(),
    }


_bridge: MqttBridge | None = None


def get_bridge() -> MqttBridge:
    global _bridge
    if _bridge is None:
        _bridge = MqttBridge()
    return _bridge


def bridge_status() -> dict:
    b = get_bridge()
    return {
        "connected": b.connected,
        "last_error": b.last_error,
        "last_connected_at": b.last_connected_at,
        "announced_entities": b.announced_entities,
    }
