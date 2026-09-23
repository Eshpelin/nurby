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

## Follow-up work

Web and Telegram update-in-place need to carry the demotion/correction and
display both timestamps. Until those channel updates are complete, the
original fast notification remains the source of truth and the event history
records the later verification result.
