# Alert latency contract

Nurby has two alert lanes with different promises:

- **Fast lane:** deterministic camera/audio detection, geometry, and rule
  evaluation. The first notification is emitted as soon as the trigger is
  accepted; it must not wait for a VLM call.
- **Narrative lane:** captions, verification, and enrichment. These may take
  tens of seconds and arrive after the first alert as an explanation or a
  correction.

Security-critical rules should use **verify-as-demotion**: notify first, then
run `verify` with `on_fail: "demote"`. A failed or unclear AI check downgrades
the event to a detection instead of suppressing the original fast alert.
This is the default for the after-hours person template. A rule must not put a
VLM `verify` before its first `notify` unless delayed notification is an
explicit product decision.

The UI should show the original alert timestamp and any later analysis
timestamp separately. `observations.vlm_late` marks analysis that waited more
than 60 seconds in the enrichment queue; it is analysis delay, not detection
delay, and should be presented as “analysis delayed.”

## Measurement

Fast-lane latency is measured from the triggering observation timestamp to the
notification delivery timestamp. Report p50 and p95 grouped by camera over a
rolling operational window. The persisted `Event.fired_at` and
`Notification.delivered_at` timestamps are the canonical source for this
measurement; a missing delivery timestamp is excluded from delivered-latency
percentiles and counted as a delivery failure.

Administrators can read the rolling report from
`GET /api/system/alert-latency?hours=24` (the window is limited to 30 days).
It returns one row per camera with p50, p95, sample count, total events, and
undelivered events. Multiple in-app delivery rows for one event count once,
using the earliest successful delivery.

## Delivery revisions

When a post-alert `verify` action completes, the original event remains
immutable as evidence of what was detected, while its linked web notification
is revised in place. The revision appends the outcome, the analysis timestamp,
and the original alert timestamp; a WebSocket `notification_updated` event
updates open dashboards immediately. A demotion changes the notification to
the quiet `info` severity but does not erase the alert or its audit trail.

Telegram alerts persist their channel and message locator on the event and are
edited in place with the same correction. If a channel is unavailable or an
edit is rejected by Telegram, the event and web notification still retain the
correction and the failure is logged; delivery revision is best-effort and
never changes the rule outcome.
