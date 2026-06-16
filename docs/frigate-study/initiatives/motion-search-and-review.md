# Initiative: Motion search + review items

**Source PRs:** #23378 (refactor motion search), #23383 (optimize motion activity endpoint),
#23359 (motion search fixes), #23307 (motion review docs), related: #23387 (hide camera from
review). **Status:** MISSING in Nurby. **Priority:** P2. **Effort:** L.

## What Frigate has

1. **Review items** — Frigate groups raw detections into "review items" (alerts vs detections)
   so the operator reviews *events*, not a firehose of frames. This is its own subsystem
   (`frigate/review/`).
2. **Motion search** — scrub a camera's timeline by *where and when* motion occurred, even with
   no object detected. Backed by a motion-activity endpoint that returns motion intensity over
   time (optimized in #23383) so the UI can render a motion heatstrip and jump to active spans.

## What Nurby has today

- Alerts/Detections tabs (review-item-*like* grouping) from the June overhaul.
- A timeline of incidents/observations.
- Motion detection at ingest (`MOTION_THRESHOLD`, motion zones) but **no persisted motion-
  activity timeline** and **no motion search/scrub** in the UI.

## Gap → plan

1. **Persist motion activity.** Record per-camera motion score over time (cheap: we already
   compute motion at ingest). Store a downsampled series (e.g. 1 value/sec) in Postgres or a
   Redis timeseries, retained like recordings.
2. **Motion-activity endpoint.** `GET /cameras/{id}/motion?from&to` → bucketed intensity.
   Mirror Frigate's optimization (#23383): aggregate server-side, return compact buckets.
3. **Timeline motion heatstrip.** Render intensity under the scrubber; click a span to seek.
4. **Motion-only review.** Let a user review spans with motion but no object (catches things
   the detector missed) — complements the existing Detections tab.

## Notes

- Reuse the existing motion pipeline; do not add a second motion detector.
- Coordinate with #23387 (hide camera from review): the same per-camera visibility flags should
  apply to the motion-search view.
