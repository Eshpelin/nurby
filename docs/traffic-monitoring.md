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
Shipped as `red_light_cross`. The "red" can now come from the camera
itself (see Phase 3 below) or, as a fallback, a manual red-window schedule
(you set the red hours; overnight windows wrap midnight).

## Phase 3 — shipped

### Automatic traffic-signal colour
Draw a zone of type **Traffic signal** over the light head. Each keyframe,
the perception pipeline samples the pixels inside that polygon, converts to
HSV, and classifies the lit lamp as red / amber / green (or unknown when
nothing is clearly lit). The state is stamped onto the rule payload as
`signal_states: {"Signal North": "red"}`. A `red_light_cross` rule with a
`signal_zone` then fires only on a *detected* red, no manual schedule
needed. Pure CV (a hue histogram in the ROI), no model, fully offline.
Accuracy depends on framing the zone tightly on the lamp; glare, backlight,
and night blur are the known failure modes, which is why ambiguous frames
report `unknown` rather than guessing.

The detected colour is also broadcast live to the dashboard: each camera
tile shows a small dot + label (red / amber / green / unknown) for every
signal zone, and the tooltip reports the per-colour lit fraction. That is
the calibration tool. Frame the zone, watch the readout against the real
light, and adjust the HSV thresholds in `services/perception/traffic_signal.py`
(`_MIN_SAT`, `_MIN_VAL`, `_MIN_FRACTION`) if a lamp reads `unknown` when lit.

```json
{ "type": "red_light_cross", "points": [[x1,y1],[x2,y2]],
  "signal_zone": "Signal North", "label": "car" }
```

### Crosswalk blocking
Trigger type **Crosswalk blocked** (`crosswalk_violation`). Draw the
crossing as a named zone; the rule fires when a vehicle and a pedestrian
occupy that zone in the same frame (the "car stopped on the zebra while
people are crossing" hazard).

```json
{ "type": "crosswalk_violation", "crosswalk_zone": "Crosswalk",
  "vehicle_label": "car" }
```

### Lane congestion
Trigger type **Lane congestion** (`lane_occupancy`). Counts vehicles inside
a named lane zone and fires at a threshold. Optionally only counts
stationary vehicles (a real backup, not free-flowing traffic), and
`sustain_seconds` requires the lane to hold over the threshold that long
before firing (frame-clock based) so a brief cluster passing through does
not trip it. `sustain_seconds: 0` (the default) fires on the first frame.

```json
{ "type": "lane_occupancy", "lane_zone": "Lane 1",
  "min_vehicles": 3, "require_stationary": true, "sustain_seconds": 5 }
```

## Phase 4 — research (new CV models)

- **Automatic lane & zebra-crossing recognition.** Today you draw these as
  zones. Auto-detection needs a lane/road-segmentation model, or a VLM that
  proposes zones you confirm. Planned as "suggest, you approve," never silent.
- **Lane change without blinker.** Detecting a turn-signal lamp blinking is a
  hard, small-object CV problem; flagged as aspirational rather than faked.
- **Full traffic-signal-state detection** across phases (protected-turn
  arrows, flashing reds), beyond the single red/amber/green sample above.

## Design notes for contributors

- Triggers live in `services/events/engine.py` `_match_trigger`. The traffic
  triggers read `rule_data["vehicle_detections"]` (plate, bbox, `zones`),
  `rule_data["tracks"]` (`prev_bbox`, `state`), and the line geometry in the
  pattern. No new perception model is invoked at rule time.
- Vehicles are stamped with their named-zone membership in
  `services/perception/pipeline.py` via `annotate_detection_zones`, the same
  bottom-center anchoring used for object detections.
- Traffic-signal colour is the one trigger input that needs pixels: it is
  computed in `services/perception/traffic_signal.py` `detect_signal_states`
  from the un-masked frame and stamped onto `rule_data["signal_states"]`.
  Everything else the engine reads is already in `rule_data`.
- Dry-run synthesis for the rule tester is in
  `services/api/routes/rules.py` `_synthesize_observation_for_trigger`.
- The builder UI is in `frontend/src/components/rules/` (`types.tsx`,
  `TriggerSection.tsx`, `RuleBuilder.tsx`, `ruleFormReducer.ts`); zones are
  drawn with the existing `GeometryEditor` / `ZoneEditorCanvas`.
- The camera persona is in `frontend/src/lib/camera-personas.ts`.
