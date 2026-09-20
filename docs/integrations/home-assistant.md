# Nurby + Home Assistant

Nurby ships a first-class Home Assistant integration over MQTT. Point
Nurby at your broker and it appears in HA as a device — no YAML, no
custom component (see `mqtt.md` for the raw topic contract if you use
Node-RED or anything else).

## Setup

1. **Broker.** You need an MQTT broker; Home Assistant needs one too,
   so if HA already speaks MQTT you already have one. Otherwise run the
   bundled Mosquitto:
   ```bash
   docker compose --profile mqtt up -d mosquitto
   ```
2. **Point Nurby at it.** Settings → MQTT: set the host (`mosquitto`
   for the bundled one, otherwise your broker's host), port, and
   credentials; enable. The **Test connection** button verifies the
   broker handshake without disturbing the live bridge.
3. **Point Home Assistant at the same broker.** HA → Settings →
   Devices & Services → Add Integration → MQTT (one-time; HA then
   listens for discovery automatically).
4. Devices appear under **Nurby** within seconds: one device per
   camera, nested under the Nurby hub device.

Renaming a camera in Nurby moves its topics but keeps its HA entities
(unique ids are derived from the stable camera UUID; discovery is
republished automatically). Deleting a camera removes its entities.

## Entities per camera

| Entity | Type | Meaning |
|---|---|---|
| Motion | binary_sensor | ON while the camera sees motion; OFF after ~30 s quiet |
| Detections | event | Fires per detection: `person`, `face`, `vehicle`, `plate`, `object`, `motion` |
| Snapshots | camera | Latest frame — updated on every observation and periodically (~10 s) |
| Detect | switch | Pause/resume object detection on that camera |
| Recordings | switch | OFF = `recording_mode: off`, ON = `always` |
| Enabled | switch | The camera's master power (stream workers stop when off) |

Hub-level: a **Cameras online** sensor (full stats as attributes) and
availability — every entity greys out when Nurby dies, including via
the broker's Last Will.

## Rich notification blueprint

`nurby-ha-notification-blueprint.yaml` in this directory imports as an
HA blueprint (Settings → Automations → Blueprints → Import Blueprint):
a person/vehicle alert with the camera snapshot attached and a
tap-through to Nurby's live view, with an after-hours condition and a
cooldown built in.

Manual equivalent:

```yaml
automation:
  - alias: "Nurby person at front door"
    trigger:
      - platform: mqtt
        topic: nurby/cameras/front-door-a1b2/events
    condition:
      - condition: state
        entity_id: binary_sensor.front_door_motion
        state: "on"
    action:
      - action: notify.mobile_app_phone
        data:
          title: "Nurby: {{ trigger.payload_json.event_type }} — {{ trigger.payload_json.camera }}"
          message: "{{ trigger.payload_json.rule_name }}"
          data:
            image: "http://nurby:4747{{ trigger.payload_json.event_url }}"
```

## Security notes

- The bundled Mosquitto allows anonymous connections for a zero-setup
  LAN start. Before exposing port 1883 beyond your LAN, enable a
  password file (`config/mosquitto.conf` has the four-line recipe) and
  set `mqtt_username`/`mqtt_password` in Nurby.
- Nurby's MQTT password is Fernet-sealed at rest and never echoed back
  by the API.
- Snapshots published over MQTT are the annotated best frames (the same
  images the timeline shows). Privacy blur still applies upstream; a
  broker reachable by others can read them, hence the lockdown note.
