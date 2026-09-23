# Monitoring coverage contract

**Issue:** #194 · **Status:** backend contract + endpoint shipped; Ask already
consumes coverage (#198); Home/recap surfaces consume `/api/coverage`.

## Why

A conclusion like "all quiet last night" is only trustworthy if we can also
say what we were able to watch. Worker health and the doctor answer "is the
process up?"; this answers "was the home actually monitored, per camera, over
this window?" so a user-facing summary never passes a coverage gap off as a
quiet period.

## The contract

`GET /api/coverage?hours=24` (authenticated, permission-scoped) returns, for
each camera the viewer may see:

- `status` - current camera status.
- `evidence_state` - the key field:
  - `active` - events observed in the window.
  - `quiet` - online, pipeline healthy, nothing happened (a trustworthy negative).
  - `outage` - offline for some/all of the window; that stretch is not quiet.
  - `unprocessed` - footage captured but the analysis pipeline was down.
- `last_observation_at` / `last_ai_caption_at` / `last_recording_at` - freshness.
- `outages` - offline intervals `[{from, to|null, reason}]` from the camera
  status log (`to: null` means still offline).
- `gaps` - human-readable, permission-safe lines for banners/recaps.

Plus a `pipeline` block (ingestion, perception, observation_writer, vlm, from
the same keys the doctor and the beacon use) and a `summary`
(`cameras_with_gaps`, `any_outage`, `fully_covered`).

## Where it is used

- **Ask** already qualifies answers with outage + retention limitations
  (`services/search/answer_scope.py`, #198) and marks a no-results answer as
  "not a confirmed quiet period" when a camera was offline.
- **Home / recaps** consume `GET /api/coverage`; `coverage_sentences(report)`
  flattens gaps into ready-to-render lines.

## Guarantees (acceptance)

- Injected failures identify the affected capability and interval: an offline
  camera yields an `outage` with its interval; a failing VLM/observation
  writer or a dead perception worker yields `unprocessed` with the reason.
- A monitoring gap cannot be summarized as an unqualified quiet period:
  `outage`/`unprocessed` override `quiet`, and are ordered ahead of it in the
  classifier.
- Coverage never exposes cameras outside the viewer's permissions: every
  query funnels through `shared.camera_access.apply_camera_filter`.

## Source

`services/perception/coverage.py` (logic), `services/api/routes/coverage.py`
(endpoint), `tests/test_coverage.py`.

## Deferred

- Per-capability freshness thresholds are intentionally conservative (we flag
  a recording gap only for `always`-mode cameras, and lean on pipeline
  component health rather than guessing "too few observations", which would
  false-alarm on genuinely quiet cameras). Tune with real deployment data.
