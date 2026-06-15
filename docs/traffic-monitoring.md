# Traffic & parking monitoring

Nurby can act as a traffic/parking camera on your own property: read plates,
control who may enter, reserve parking spots, and flag wrong-way driving.
Everything is built on the existing pipeline (vehicle detection, plate OCR,
the object tracker, named zones, the rule engine) — there is no separate
"traffic engine" to learn. You point a camera at a street, driveway, or
garage, pick the **Traffic / parking** persona, draw a few zones, and write
rules.

## What ships today (Phase 1)

### Traffic / parking camera persona
One click in camera settings configures the camera for vehicles: object
detection on, plate reading on (automatic for car/truck/bus/van/motorcycle),
outdoor scene mode, record-on-vehicle, and event summaries tuned to traffic.
You can override anything afterward.

### Plate list — access control
Trigger type **Plate list**, two modes:

- **Block-list**: alert when a banned plate appears. (The ex-tenant's car,
  a known nuisance vehicle.)
- **Allow-list**: alert on any vehicle whose plate is *not* on your list.
  This is garage/driveway access control — list your household's plates and
  Nurby tells you when a stranger pulls in. Optionally also flag vehicles
  whose plate can't be read.

Plate matching ignores spacing and case. Trigger pattern:

```json
{ "type": "plate_list", "mode": "allowlist" | "blacklist",
  "plates": ["ABC123", "XYZ789"], "substring": false, "require_plate": true }
```

### Parking spot reservation
Trigger type **Parking spot**. Draw a parking space as a named zone in the
camera's *Zones & Tripwires* settings, then make a rule: reserve the spot for
your plate(s) and Nurby alarms when anyone else parks there. Leave the
reserved list blank to alert whenever *any* vehicle parks in the spot. The
"only when actually parked" option waits for the vehicle to stop (via the
tracker's stationary state) so a car merely passing through the spot does not
trip it.

```json
{ "type": "parking_violation", "spot_zone": "Spot A",
  "reserved_plates": ["MYCAR1"], "require_stationary": true }
```

### Wrong-way / reverse driving
Trigger type **Wrong way**. Draw a line across a lane and pick the legal
direction of travel; the rule fires on a vehicle crossing the *other* way.
Built on the same directional-crossing math as tripwires.

```json
{ "type": "wrong_way", "points": [[x1,y1],[x2,y2]],
  "allowed_direction": "in", "label": "car" }
```

All three triggers work in the rule builder's **Run test** dry-run and the
historical replay, compose with the existing condition/action chain (notify,
email, Telegram, webhook, siren via ESP32, AI verify gate), and respect
cooldowns and snooze.

## Phase 2 — shipped (user calibration required)

### Speed estimation
Pixel displacement alone is not speed; the camera has no sense of real-world
distance. Shipped as a **two-line speed gate** (`speed_over` trigger): the
user draws two lines a known real distance apart and enters that distance.
The engine times a tracked vehicle between the two crossings and computes
average speed. Accuracy is roughly ±10–20% (camera angle, where the bbox
anchor sits) — good enough for "someone is flooring it down my street," not
for legal citations.

```json
{ "type": "speed_over", "line_a": [[x,y],[x,y]], "line_b": [[x,y],[x,y]],
  "distance_m": 10, "min_speed_kmh": 30, "label": "car" }
```

### Red-light / signal running
Shipped as `red_light_cross`: a stop-line crossing gated by a manual
red-window schedule (you set the red hours; overnight windows wrap
midnight). Detecting the signal lamp's colour automatically (HSV in a
user-drawn zone, or a VLM check) remains Phase 3.

## Phase 3 — research (new CV models)

- **Automatic lane & zebra-crossing recognition.** Today you draw these as
  zones. Auto-detection needs a lane/road-segmentation model, or a VLM that
  proposes zones you confirm. Planned as "suggest, you approve," never silent.
- **Lane change without blinker.** Detecting a turn-signal lamp blinking is a
  hard, small-object CV problem; flagged as aspirational rather than faked.
- **Full traffic-signal-state detection** across phases.

## Design notes for contributors

- Triggers live in `services/events/engine.py` `_match_trigger`. The traffic
  triggers read `rule_data["vehicle_detections"]` (plate, bbox, `zones`),
  `rule_data["tracks"]` (`prev_bbox`, `state`), and the line geometry in the
  pattern. No new perception model is invoked at rule time.
- Vehicles are stamped with their named-zone membership in
  `services/perception/pipeline.py` via `annotate_detection_zones`, the same
  bottom-center anchoring used for object detections.
- Dry-run synthesis for the rule tester is in
  `services/api/routes/rules.py` `_synthesize_observation_for_trigger`.
- The builder UI is in `frontend/src/components/rules/` (`types.tsx`,
  `TriggerSection.tsx`, `RuleBuilder.tsx`, `ruleFormReducer.ts`); zones are
  drawn with the existing `GeometryEditor` / `ZoneEditorCanvas`.
- The camera persona is in `frontend/src/lib/camera-personas.ts`.
