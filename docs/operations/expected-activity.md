# Expected activity: alert on the absence of expected life

**Issue:** #215 · **Status:** core shipped (model + API + scheduler + alerts). Templates/onboarding, expected-visitor auto-learning, and a rich recap view deferred.

## Why

Every NVR is an event machine: rules fire on detections, and *absence* is
unrepresentable. But "Mom didn't reach the kitchen by 10:00", "nobody came
home by 17:30", "the cleaner missed her Tuesday window" are the highest-value
things a VLM+identity platform can say that a traditional NVR cannot —
"expected" is computable because Nurby knows who people are.

## How it works

An **expectation** (`expected_activities`) is a scheduled window, not a frame
rule:

- `subject_kind` — `person` (a named person must appear), `any_person`, or
  `any_activity` (any observation, motion counts).
- `camera_ids` — the place (empty = any camera).
- `weekdays` + `start_time`/`end_time` (local, overnight supported) + `grace_minutes`.
- `active_modes` — household modes it applies in (#184). Null = all; a common
  setup is `["home","night"]` so an away day is not a nobody-home alarm.

The **sweeper** (`services/perception/expected_activity_sweeper.py`) runs every
5 min off the frame loop. For each enabled expectation whose window has closed
(end + grace) and hasn't been evaluated today, it gathers the window's
sightings and its **coverage** (#194), then runs the pure decision
`services/perception/expected_activity.evaluate_window`:

- `satisfied` — a matching sighting exists → silence.
- `violated` — the window was **covered** and nothing expected happened → an
  in-app alert with evidence (last-seen, window, what was checked).
- `unknown` — the window was **not fully covered** (a camera was
  offline/degraded) → no alert; absence is never asserted over a gap.
- `not_applicable` / `skipped_mode` — wrong weekday, or the household was in a
  mode this expectation does not watch.

The outcome + date are stored on the row (`last_status`, `last_evaluated_on`)
for dedupe (one evaluation per window) and a simple recap.

## API (`/api/expected-activity`, permission-scoped)

`GET` (list with each one's `last_status`), `POST`, `PATCH /{id}`,
`DELETE /{id}`. A user may only create/see expectations whose cameras they can
all see; a no-camera ("any") expectation is visible to everyone.

## Acceptance

- Define an arrival/window and get an alert on failure, with last-seen evidence
  and coverage honesty ✅.
- A normal week produces zero alerts for satisfied expectations (dedupe + the
  `satisfied`/`unknown` branches) ✅.
- Satisfied vs violated visible in a recap: the list endpoint returns each
  expectation's `last_status` ✅ (a richer digest view is deferred).

## Deferred

- Expected-**visitor** auto-learning (recurring known visitors become
  "expected" so their normal arrival is silence and their absence is signal).
- Templates (elder check-in, school arrival, expected visitor) wired into
  goal-based onboarding.
- A dedicated recap/digest panel; sharing the eldercare check-in core with
  Guardian (#191).
- Delivery beyond the in-app Notification (push/telegram/email) — the alert is
  persisted + marked delivered in-app today.

Source: `shared/models/rules.py` (`ExpectedActivity`, migration
`b5d7f9a1c3e5`), `services/perception/expected_activity.py` (decision),
`_sweeper.py` (schedule), `services/api/routes/expected_activity.py` (API),
tests `tests/test_expected_activity*.py`.
