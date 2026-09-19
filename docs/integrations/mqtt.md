# MQTT integration

Nurby speaks MQTT so it plugs into the ecosystem every other self-hosted
camera/automation tool already shares: Home Assistant, Node-RED, ESPHome,
n8n, double-take, Zigbee2MQTT brokers. Point Nurby at a broker and it
publishes a stable, documented topic tree plus Home Assistant MQTT
discovery configs, so Nurby's cameras appear in Home Assistant as real
devices — motion sensors, event entities, camera tiles, and control
switches — with zero YAML.

The design follows Frigate's MQTT conventions (a small, stable topic
contract; one availability topic with a Last Will; retained `/state`
mirrors of every `/set` command; snapshots as raw JPEG on their own
topic) and adds Home Assistant discovery emission (the Viseron /
Scrypted approach) because Nurby has no HA companion integration —
discovery is what makes it work out of the box.

## User stories

1. As a Home Assistant user, I enter my broker host and credentials in
   Nurby settings, and my cameras appear under a "Nurby" device with
   motion sensors, event entities, camera tiles, and switches — no YAML.
2. As a Home Assistant user, when a person is detected at the front door
   after 22:00, an automation sends a rich notification with the
   snapshot attached and a tap-through to the live view.
3. As a Home Assistant user, I flip a switch to pause detection or
   recordings on a camera; the state is retained, survives restarts,
   and Home Assistant shows the true state after a reconnect.
4. As a Home Assistant user, availability tracking tells me when Nurby
   or a camera is offline.
5. As a Node-RED / n8n user, I subscribe to `nurby/#` and build my own
   automations against a documented topic contract whose event payloads
   match the existing webhook payloads.
6. As a new self-hoster without a broker, I enable the bundled Mosquitto
   compose profile and everything works.

## Enabling it

Settings → MQTT (or `PATCH /api/system/settings`):

| Key | Default | Meaning |
|---|---|---|
| `mqtt_enabled` | `false` | Master switch. When false nothing connects or publishes. |
| `mqtt_host` | `""` | Broker hostname (e.g. `mosquitto` on the compose network, or `homeassistant.local`). |
| `mqtt_port` | `1883` | Broker port. |
| `mqtt_username` / `mqtt_password` | `""` | Optional auth. The password is Fernet-sealed at rest and never echoed back by the API. |
| `mqtt_tls` | `false` | Connect with TLS. |
| `mqtt_topic_prefix` | `nurby` | Root of Nurby's topic tree. Change it to run several Nurby instances against one broker (give each a unique `client_id` too, like Frigate). |
| `mqtt_client_id` | `nurby` | MQTT client id. |
| `mqtt_discovery_enabled` | `true` | Emit Home Assistant discovery configs. |
| `mqtt_stats_interval` | `60` | Seconds between `stats` publishes. |
| `mqtt_camera_frame_interval` | `10` | Seconds between periodic JPEG publishes on `cameras/{slug}/snapshot` (0 disables; detection snapshots are always published). |

No broker? Enable the bundled one:
`docker compose --profile mqtt up -d` starts eclipse-mosquitto on 1883
(see `docker-compose.mqtt.yml`); then set `mqtt_enabled=true` and
`mqtt_host=mosquitto`.

## Topic contract (prefix configurable, default `nurby`)

| Topic | Retained | Payload |
|---|---|---|
| `{prefix}/status` | yes (LWT) | `online` birth on connect, `offline` will on ungraceful loss, `stopped` on graceful shutdown. |
| `{prefix}/stats` | no | JSON snapshot: `{cameras_total, cameras_online, cameras_recording, uptime_seconds, timestamp}`. Published every `mqtt_stats_interval`. |
| `{prefix}/events` | no | One JSON per fired rule event, same shape as the documented webhook payload (`docs/webhooks.md`): `event_id, rule_id, rule_name, camera_id, camera_name, timestamp, motion_score, object_detections, person_detections, vlm_description, observation_id, recording_id, recording_url, thumbnail_url, event_url`. |
| `{prefix}/cameras/{slug}/events` | no | Compact event entity payload: `{"event_type": "person", "event_id": ..., "label": ..., "confidence": ..., "camera": ..., "timestamp": ...}`. |
| `{prefix}/cameras/{slug}/motion` | no | `ON` while motion, `OFF` after 30 s of quiet (Frigate's `motion_off_delay` behaviour). |
| `{prefix}/cameras/{slug}/snapshot` | no | Raw JPEG bytes. Published on every new observation (best frame) and periodically every `mqtt_camera_frame_interval` seconds. |
| `{prefix}/cameras/{slug}/detect/set` + `/state` | state yes | `ON`/`OFF` command; retained state mirror of `Camera.detect_objects`. |
| `{prefix}/cameras/{slug}/recordings/set` + `/state` | state yes | `ON`/`OFF`; state mirror of `Camera.recording_mode != "off"`. `ON` sets mode `always`, `OFF` sets mode `off`. |
| `{prefix}/cameras/{slug}/enabled/set` + `/state` | state yes | `ON`/`OFF`; retained state mirror of the camera master enable. |

`{slug}` is the camera name slugified with a short id suffix
(`Front Door` + uuid `a1b2…` → `front-door-a1b2`): readable like
Frigate's topics, stable and collision-free without coordination. The
slug changes when a camera is renamed; HA entities do not, because
their `unique_id`s are derived from the camera UUID and discovery is
republished under the new topics.

QoS: events/motion/snapshots fire at QoS 1 (a dropped detection is
worse than a duplicate — de-duplicate on `event_id`), motion at QoS 0,
status/state/discovery at QoS 1 retained.

## Home Assistant discovery

When `mqtt_discovery_enabled` is true, the bridge publishes retained
discovery configs under `homeassistant/...`:

- **Hub device first**: `identifiers: ["nurby"]`, name "Nurby",
  model/manufacturer/sw — HA requires the hub device to exist before
  children referencing it via `via_device`.
- **Per camera** (device `identifiers: ["nurby_{camera_id}"]`,
  `via_device: "nurby"`):
  - `binary_sensor` *motion* (`device_class: motion`) on
    `cameras/{slug}/motion`.
  - `event` entity *detections* (`event_types` from Nurby labels:
    person, vehicle, face, plate, …) on `cameras/{slug}/events`.
  - `camera` entity fed by the raw-JPEG `cameras/{slug}/snapshot`
    topic.
  - `switch` *detect*, *recordings*, *enabled*: `command_topic`
    `.../set`, `state_topic` `.../state`.
- **Global** `sensor` reading `{prefix}/stats` with a
  `value_template` and JSON attributes.
- Every entity carries `availability_topic: {prefix}/status`
  (`online`/`offline`), so entities grey out when Nurby dies —
  including via the broker-published Last Will.
- When Home Assistant restarts it publishes `online` to
  `homeassistant/status`; Nurby re-announces all discovery configs and
  retained states on that signal (the ESPHome coordination pattern), so
  entities come back without touching Nurby.
- Removing a camera or disabling the integration publishes empty
  payloads to the config topics, which deletes the HA entities.

## Architecture

One MQTT client (aiomqtt, asyncio-native) runs as a supervisor in the
API process — the same lifecycle pattern as the Telegram poller
manager. Other processes publish through a small Redis pub/sub bus
(`nurby:mqtt:out`, `shared/mqtt_bus.py`), mirroring how rule firings
reach the WebSocket relay. The bridge:

- maintains the connection, birth/will, resubscription and retained
  replay across reconnects (exponential backoff),
- drains the bus and forwards messages to the broker, buffering the
  last retained value per topic so state survives a broker outage,
- tracks motion activity to emit the delayed `OFF`,
- reconciles discovery + state mirrors against the camera table,
- routes `*/set` commands to camera settings (with a stream-restart
  signal for the ingestion manager) and watches `homeassistant/status`.

Producers: rule firing (`services/events/firing.py`) publishes events;
the ingestion stream worker publishes motion + periodic frames
(`services/ingestion/mqtt_out.py`); the perception pipeline publishes
observation snapshots; the bridge publishes stats and state mirrors.

## Not in this iteration

Inbound MQTT sources (consuming `frigate/events`, Blue Iris, Scrypted
or custom JSON into Nurby's pipeline) are deliberately out of scope;
the single shared client and the topic/payload builders are structured
so a `sources/` module can subscribe and parse later without
redesigning anything.
