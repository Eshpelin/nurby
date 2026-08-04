# Industrial & workplace automation: OpenVector teardown and Nurby plan

Date: 2026-08-04
Source: full read of https://openvector.com (home, /how-it-works, /research, /about, /order)
plus their client-side data files (`/js/scenarios.js`, `/js/integrations.js`).

This doc has three parts:

1. What OpenVector actually says and shows, captured verbatim.
2. What Nurby can already do, checked against the code, not against memory.
3. What to build, ordered by leverage.

---

## 1. What OpenVector is

### Positioning

> "an ai that lives in your camera to take action."

The whole site is built around one shift: **camera → action**, not camera → alert.
Their three-word story is **Watch. Understand. Act.** Every proof point on the page
ends in a side effect in somebody else's software, never in a notification.

The second pillar is **it acts inside the systems your industry already runs**:

> "OpenVector turns camera events into actions in the operational system of record
> behind gyms, car washes, offices, warehouses, and restaurants."

### The six playground scenarios (verbatim rule text)

These are the examples we want equivalents for. Taken from `scenarios.js`.

| Cam | Place | Detection | Rule (their words) | System acted in |
|---|---|---|---|---|
| CAM-01 | Main Lobby | `TAILGATE 0.94` | "When someone tailgates in through the main lobby, call my phone." | Phone call, cross-checks Brivo badge logs |
| CAM-02 | Member Gate | `TAILGATE 0.91` | "When someone tailgates through the member gate, add a $50 guest fee and email me the report." | Mindbody |
| CAM-03 | Entry Lane | `PLATE-MATCH 0.92` | "When a plate matches a wash-club member at the entry lane, apply their loyalty discount." | DRB SiteWatch, discount applied at POS |
| CAM-04 | Service Lane | `PLATE 0.93` | "When a car pulls into the service lane, open a repair order and assign an advisor." | CDK Global |
| CAM-05 | Assembly Line | `BOTTLENECK 0.89` | "Every evening at 6pm on the assembly line, send me a WhatsApp report on bottlenecks, downtime, and cycle time." | WhatsApp |
| CAM-06 | Aisle 7 | `MIS-SLOT 0.88` | "When a pallet is put away in the wrong rack in aisle 7, call me." | WMS flagged, phone call |

Note the split: **4 of 6 are commercial/industrial, 0 of 6 are residential.** Nurby's
nine starter templates are the exact inverse.

Also note the agent "reply" line under each rule. It is written as a coworker
explaining its own plan, e.g.:

> "I'll track the pallet to its rack, flag the WMS, and call when it is mis-slotted."

That reply is doing real persuasion work. It is the moment the product stops
reading as a detector and starts reading as a hire.

### The rule-building flow (/how-it-works)

Four steps: **Describe the rule → OpenVector builds it → Review the agent → Keep it running.**

The "agent card" they render at step 3 has exactly four slots:

- **stream** — video input, pick an RTSP stream
- **if** — natural-language condition + a *minimum confidence* slider (shown at 92%)
- **then** — action, with a row of connectable systems (DRB SiteWatch, Twilio, Gmail, Webhook)
- **and** — "completed work": *Apply at POS · Log the visit · Update member profile · Make searchable*

Then a live activity log:

```
09:14  Plate matched a wash-club member. Loyalty discount applied at the POS
09:14  Member profile updated. Visit logged
09:15  Event indexed and searchable in the dashboard
```

Two things worth stealing outright:

1. **The confidence slider is a first-class rule field in the UI.** It makes the rule
   feel tunable and honest about uncertainty.
2. **"Completed work" is separated from "the action."** The action is the business
   effect; the completed work is the bookkeeping (log it, index it, make it
   searchable). Nurby does all the bookkeeping already and gets zero credit for it
   because it is never named.

### The integrations wall (`integrations.js`)

Twelve system *categories*, each with an industry and named vendors. The framing is
category-first, vendor-second, with the line **"Works with any CRM you run."**

| Acronym | System | Industry | Named vendors |
|---|---|---|---|
| CRM | Customer Relationship Management | Gyms & multi-site | Mindbody, Salesforce, HubSpot |
| ACS | Access Control System | Unstaffed gyms | Brivo, Verkada |
| POS | Point of Sale | Car wash | DRB |
| TCS | Tunnel Control System | Car wash | DRB |
| PACS | Physical Access Control | Commercial security | Genetec, Avigilon, Brivo |
| HRIS | HR Information System | Corporate HR | Workday, Rippling, BambooHR |
| VMS | Visitor Management | Corporate office | Envoy, Sign In App |
| IWMS | Integrated Workplace Mgmt | Corporate office | Eptura, Envoy |
| ERP | Enterprise Resource Planning | Warehousing & corporate | SAP, Oracle, Dynamics 365 |
| WMS | Warehouse Management | Warehousing | SAP EWM, Oracle WMS |
| POS | Point of Sale | Restaurant | Toast, Square |
| KDS | Kitchen Display System | Restaurant | Toast, Fresh KDS, Square KDS |

This is the single highest-ROI thing on their site and it is **almost entirely a
copy exercise**. Underneath, most of these are an authenticated HTTP call. Nurby's
`api_call` action already makes every one of them reachable. We just never said so.

### The research page (their moat claim)

Foveated sampling, framed as "seeing more with less":

- CVPR 2025 Spotlight, "Seeing More with Less: Human-like Representations in Vision Models"
- A lightweight sub-sampler sits between camera and vision model, picks the regions
  worth full detail, and the model's attention feeds back to steer the next fixation
- ~3% of pixels retains roughly 80% of full-frame performance
- 5–10× less bandwidth for IoT cameras, body cams, wearables
- 45 kB for a 720p frame vs 1.3 MB
- +2–3% accuracy on visual QA/detection at that budget
- Task-agnostic, no retraining, drops in front of BLIP-2, LLaVA, ViLT
- Streams intelligibly inside a 70 kbit/s link, so the model runs *on the camera*

Their /about says they are "obsessed with bringing **self-improving** visual
intelligence to the physical world." That is the learning claim, and note that it
is a claim about the *perception layer* steering its own attention, not about the
rules learning from user corrections. Both stories are available to us. Ours can
be stronger because we own the feedback surface.

### Business model signals (/order)

- "OpenVector Station", $100 refundable deposit
- $449/month **or** $6,499 up-front, billed at delivery
- California, Fall 2026, in-person setup, "no assembly or configuration required"
- Demo CTA: "we'll turn one of your live streams into a working automation on the call"

They are selling an appliance with a truck roll. We are selling software you run
yourself. That is a real differentiator to lean on, not a weakness.

---

## 2. What Nurby actually has today

Checked against `shared/rule_schema.py`, `services/events/`, `frontend/src/lib/rule-templates.ts`,
`integrations/devices/catalog.py`.

### Triggers (23)

**Vision:** `object_detected` (label, zones, moving/stationary, K-of-N persistence,
min/max area %, min/max aspect ratio), `findanything` (free-text prompt),
`vehicle_detected` (plate substring, identified-only), `plate_list`.

**Faces:** `face_detected`, `face_recognized`, `face_unknown`.

**Spatial:** `loitering` (polygon + threshold seconds + label filter),
`line_cross` (2-point tripwire, direction in/out/any, label filter).

**Traffic:** `parking_violation`, `wrong_way`, `speed_over`, `red_light_cross`,
`crosswalk_violation`, `lane_occupancy`.

**Motion/audio:** `motion`, `audio_event`, `clap_pattern`, `speech_phrase`.

**System:** `camera_offline`, `camera_online`, `incident_started`, `incident_ended`
(fires once with duration, count, and an AI recap), `any`.

Plus **sequence rules**: multi-step temporal rules with zone and loiter step kinds
and an `on_timeout` branch.

### Actions (10)

`webhook`, `api_call` (GET/POST/PUT/PATCH/DELETE, templated URL/headers/body),
`broadcast`, `notify`, `email`, `telegram` (with inline ack/mute/snooze/open buttons),
`vlm_call` (bind a VLM answer to a variable), `verify` (AI second opinion),
`locate` (FindAnything visual condition), `device` (registered physical device).

Conditions layer on top: camera allow-list, days of week, time window, cooldown.
Actions chain, and later actions can reference `{{vars.*}}` written by earlier ones.

### Devices

Four: ESP32 buzzer, ESP8266 relay lights, Raspberry Pi speaker, Raspberry Pi relay alarm.

### Starter templates (9, all residential)

Package arrives · unknown face at night · someone at the door · car in driveway ·
car not on my list · baby crying · someone calls for help · someone I know arrives ·
camera goes offline. Categories: `delivery | security | vehicles | audio | system`.

### Honest verdict

**The engine is not the gap.** Four of OpenVector's six flagship scenarios are
expressible in Nurby today with zero new engine code:

- **CAM-03 plate → loyalty discount** = `vehicle_detected(plate)` or `plate_list` → `api_call` to the POS. Buildable now.
- **CAM-04 car in service lane → open repair order** = `object_detected(car, zones=[service_lane])` → `api_call`. Buildable now.
- **CAM-06 mis-slotted pallet** = `line_cross` on the rack aisle → `locate`/`vlm_call` asking "is this pallet in rack 7B?" → `api_call` + `notify`. Buildable now, and `verify` gives it a second opinion before it wakes anyone.
- **"If you see my car open the gate, if you see someone else's don't"** = `plate_list` allow-list → `device` relay. Already a shipped template, just phrased for a driveway instead of a yard gate.

What is genuinely missing is listed next.

---

## 3. Gaps, ordered by leverage

### G1. Positioning and vocabulary — pure copy, zero engineering

Every user-facing string in Nurby says home. README opens "An AI layer for your
security cameras… where was the dog last night… stranger at the door 2am."
Template categories are Deliveries/Security/Vehicles/Sound/System health. There is
not one occurrence of *tailgate, gate, pallet, forklift, PPE, hard hat, bay, aisle,
line, shift, or throughput* anywhere in the codebase.

A buyer evaluating Nurby for a warehouse currently has to do the translation
themselves, and they won't.

**Fix:** rewrite the positioning line, add a workplace/industrial section to the
README with the same "rule sentence → what happens" table format OpenVector uses,
and add the vocabulary to the NL rule builder's prompt so "tailgate" and
"mis-slot" compile to something sensible instead of confusing the model.

### G2. No workplace or industrial starter templates

Nine templates, all residential. This is the fastest visible win in the whole doc.

**Fix:** two new categories, `workplace` and `industrial`, and ~12 templates that
use only triggers and actions that exist today. Concrete list in §4.

### G3. Named integrations — the connector concept

`api_call` can already hit Brivo, Toast, SAP, Mindbody, anything. But the UI
presents an empty URL box, so the product reads as "you have a webhook" rather
than "it works with your POS." OpenVector's entire integrations wall is a
presentation layer over the same primitive.

**Fix:** a `connector` object — name, logo, base URL, auth (bearer/basic/header),
and a small set of named operations with pre-shaped payloads. A rule action then
picks `connector + operation` instead of typing a URL. Ship the category framing
("works with any ACS you run") so we are not claiming certified partnerships.
This is a settings screen and a JSON catalog, not an integration team.

### G4. No learning loop at all

Grepped for feedback, false_positive, thumbs, correction: nothing exists. Not one
table, not one endpoint. Meanwhile OpenVector is already claiming "self-improving."

This is the biggest strategic gap and also our biggest opening, because their
"self-improving" is about pixel budgets inside the model. Ours can be about the
rule getting better because *the user corrected it*, which is far more legible to a
buyer and something we are structurally better placed to do, since we own the
event review surface, the recordings, and the rule.

**Fix, staged:**

- **L1 — capture.** A thumbs up/down (or "this was wrong") on every rule-fired
  event, stored in a `rule_feedback` table with the observation snapshot and the
  reason. Cheap. Immediately useful as a metric even before anything consumes it.
- **L2 — tune.** Per-rule confidence and dwell thresholds auto-suggested from the
  feedback history. "This rule fired 40 times, you dismissed 31. Raising minimum
  confidence to 0.86 would have suppressed 28 of them and kept all 9 you kept."
  Suggest, do not silently apply.
- **L3 — teach the VLM.** Negative and positive examples get appended as few-shot
  context to the `verify` and `vlm_call` prompts on that rule. This is where
  "your agent gets smarter" becomes literally true and demonstrable.
- **L4 — propose.** The agent watches the event stream and proposes rules:
  "a truck backs into bay 3 every weekday around 07:10. Want a rule?"

L1–L3 is a shippable arc. L4 is the demo that sells the company.

### G5. No scheduled or aggregate rule trigger

Every Nurby trigger is instantaneous. CAM-05 ("every evening at 6pm, report on
bottlenecks, downtime, and cycle time") has no equivalent. Scheduled *reports*
exist in `services/api/report_scheduler.py`, but they are a separate feature that
is not rule-addressable and is not metric-aware.

**Fix:** a `schedule` trigger kind (cron or time-of-day + days) whose context is an
aggregate over the preceding window, so the same action set can consume it.

### G6. No industrial metric primitives

Related to G5 but separable. Industrial buyers ask for counts, rates, and
durations, not events:

- throughput — objects crossing a tripwire per hour, per shift
- cycle time — time between tripwire A and tripwire B for the same track
- dwell / station time — time a track spends in a zone, aggregated
- downtime — a zone with an expected occupancy that goes empty for N minutes
- queue length — count of persons in a zone over time

`loitering` gives single-track dwell. `lane_occupancy` gives a congestion signal.
Neither aggregates. This is the substantive engineering item on the list.

### G7. Tailgating is not a first-class trigger

Their two headline scenarios are both tailgating. We can approximate it with a
sequence rule, but there is no "N people through one opening within T seconds"
primitive, and no seam to correlate with a badge event.

**Fix:** `tailgate` trigger = tripwire + `max_persons_per_event` + window. Plus an
inbound webhook endpoint so an ACS can post "badge X opened door Y at T", giving
the correlation OpenVector implies with Brivo. The inbound seam is worth more than
the trigger.

### G8. No marketing site in this repo

`frontend/` is the product dashboard. There is no landing page here, so "add
industrial use cases to the website" has no home in this codebase yet. Flagging
rather than assuming — see the open question at the end.

---

## 4. Concrete build list

### Now (copy + templates, days not weeks)

**A. Two new template categories and 12 templates**, all using shipped primitives:

*Workplace*

1. **Tailgating at the badge door** — sequence rule: `line_cross(person, direction=in)` then a second person crossing within 5s → `notify` + `telegram` with clip. Precursor to a real `tailgate` trigger.
2. **Guest fee for a piggybacked entry** — same trigger → `api_call` POST to the CRM/billing endpoint + `email` the report. This is CAM-02, ours.
3. **My car opens the gate** — `plate_list(allow)` → `device` relay. Any other plate → `notify` only.
4. **Unlisted vehicle at the gate** — `plate_list(deny/unlisted)` → `telegram` with ack button, gate stays shut.
5. **After-hours presence in the office** — `object_detected(person)` + time window 19:00–06:00 → `verify` → `notify`.
6. **Loading dock occupied too long** — `loitering(zone=dock, label=truck, threshold=1800)` → `api_call` + `email`.
7. **Visitor at reception with no one at the desk** — `object_detected(person, zones=[lobby])` + `face_unknown` → `notify` + `device` chime.

*Industrial*

8. **Pallet in the wrong rack** — `line_cross(aisle)` → `locate("pallet in rack 7B")` → `verify` → `notify` + `api_call` to WMS. This is CAM-06.
9. **PPE check at the line entrance** — `line_cross(person)` → `vlm_call("is this person wearing a hard hat and hi-vis vest?")` → `notify` on no.
10. **Person in the machine exclusion zone** — `loitering(zone=hazard, label=person, threshold=2)` → `device` relay (e-stop or beacon) + `notify` critical.
11. **Line stopped** — no `object_detected` in the conveyor zone for N minutes. *Needs G5/G6 absence-over-window.* Ship as a sequence rule with `on_timeout` in the interim, which is exactly what `on_timeout` was built for.
12. **Forklift and pedestrian in the same aisle** — sequence: `object_detected(person, zones=[aisle7])` then `object_detected(truck, zones=[aisle7])` within 10s → critical `notify` + `device`.

Each template ships with the OpenVector-style one-liner ("When a pallet is put away
in the wrong rack in aisle 7, call me") as the card blurb, so the gallery reads as
sentences rather than as a trigger taxonomy.

**B. README and positioning rewrite.** Keep the home story, add a workplace/industrial
section above it with the rule-sentence table. Lead with the differentiator
OpenVector cannot match: **self-hosted, open source, no appliance, no truck roll,
your footage never leaves your hardware.** They are asking $449/month and a
California-only Fall 2026 delivery for a box. That is a lot of room.

**C. NL builder vocabulary.** Add the industrial nouns and verbs to the rule-NL
prompt with worked examples, so "flag a mis-slotted pallet in aisle 7" compiles
instead of returning a shrug.

### Next (product surface, weeks)

**D. Connector catalog (G3)** — settings screen, JSON catalog, category-first
framing, `api_call` underneath. Ship with ACS, PACS, POS, CRM, WMS, ERP categories
and a "+ your own" escape hatch, mirroring their line.

**E. Confidence as a visible rule field.** We have thresholds internally; surface
one slider per rule the way they do. It makes the rule feel tunable and sets up L2
of the learning loop.

**F. "Completed work" panel on the rule card.** We already record the event, store
the clip, and index it for Ask. Name it on the rule summary card the way they do:
*acted · logged · clip saved · searchable*. Zero backend work, meaningful
perception change.

**G. Feedback capture (L1).** `rule_feedback` table, thumb control on the event row.

### Then (engine, the real work)

**H. `schedule` trigger with window aggregates (G5).**

**I. Metric primitives (G6):** throughput, cycle time between two tripwires, zone
dwell aggregation, absence/downtime. These unlock templates 11 and the whole
"6pm report on bottlenecks and cycle time" class.

**J. `tailgate` trigger + inbound ACS webhook (G7).**

**K. Learning loop L2 → L3 (G4).** Threshold suggestions from feedback, then
few-shot examples fed into `verify`/`vlm_call` per rule.

**L. Rule proposals from observed patterns (L4).** The demo that sells it.

---

## 5. The one-line story to converge on

OpenVector: *an AI that lives in your camera to take action.*

Nurby's answer should not be a copy. Theirs is an appliance you rent that reaches
into your SaaS. Ours is:

> **Your cameras, your hardware, your rules. Nurby watches, decides, and acts —
> at home or on the floor — and gets better every time you correct it.**

The last clause is the part they cannot say, because they do not own the
correction surface. Build G4 and it is true.

---

## Open question

Where does the marketing site live? It is not in this repo (`frontend/` is the
product dashboard). The copy work in §4B needs a target. If there is no site yet,
the README plus a `docs/use-cases/` set is the interim front door, and the
template gallery is doing the marketing inside the product.
