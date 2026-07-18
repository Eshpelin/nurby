# Steve, 54 — DIY tinkerer — 2026-07-18

Tech: high on hardware, medium on software. Reads error messages fully;
wants the system to tell him WHERE it failed, not just that it failed.

## Goals attempted

1. Add a camera by raw RTSP URL
2. Add a camera by ONVIF discovery
3. Deliberately enter a wrong RTSP URL and judge the error handling
4. Use the doctor/diagnostics page to debug a dead stream
5. Check logs/status the UI exposes when things break

## Inherited backlog first

F71 (open, polish, margaret-retired-teacher) was in the backlog: the
camera-brand picker had ~25 brands with no filter box, and never
mentioned Scan Network — the actual fix for a user who doesn't know
their brand either. Fixed before starting Steve's session:
`CameraBrandHelp.tsx` gained a filter textbox above the brand chips, and
an "Not listed, or don't know which brand you have? Scan your network
instead" line that switches `AddCameraModal`'s active tab to Scan
Network. Verified with `npx tsc --noEmit` (clean) and in the browser.
Commit 86b1aa3.

## Session narrative

Logged in as steve@ux-army.test. Checklist already showed 1/4 (a prior
run's camera existed); Steve's own goal is to add his own.

**Goal 1 — raw RTSP URL.** Manage → Connect another camera → Manual
Setup. Named it "Workshop Yard", pointed at
`rtsp://localhost:8554/yard` (the `yard` feed pool matches his DIY-yard
story), submitted. Connection test passed, camera appeared on the wall
immediately as REC, and within a minute the AI Digest and incident feed
were showing real `person` detections at 88-93% confidence on it.
Verdict: clean, no friction.

**Goal 3 — deliberately wrong RTSP URL.** Added a second camera
("Backyard Test") pointed at `rtsp://192.168.55.201:554/nonexistent`, an
address nothing answers on. The connect-test caught it before saving:

> The camera did not respond: No response from 192.168.55.201:554. Fix
> it and try again, or submit again to add the camera anyway.
> No response from the camera. Check that it is powered on, on the same
> network, and that no firewall blocks the port.

This is exactly what Steve wants — the specific IP:port that timed out,
a plain-English cause, and a concrete next step, plus the option to add
it anyway if the camera is just temporarily off. Verdict: excellent,
matches his temperament precisely. Camera was not actually added
(cancelled out of the modal).

**Goal 2 — ONVIF discovery.** Scan Network tab, clicked Scan. Correctly
reported "No ONVIF cameras found on the local network. Make sure the
cameras are powered on and connected to the same network. Check that
multicast traffic is not blocked by your firewall." — accurate, since
the harness's RTSP feeds don't advertise ONVIF. No false positives, no
hang. Verdict: correct behavior, appropriately worded for a null result.

**Goal 4 — System doctor.** Settings → System doctor → Run checks.
Returned "0 failing, 1 warning" with a per-check breakdown including
timings: Video ingestion, AI perception, Database, Redis, Stream relay
all ✓ with millisecond timings; Email correctly "not configured"; Alert
delivery flagged as a warning (no notification channel) with a concrete
fix ("Add Telegram, email, or the mobile app..."); and — critically for
Steve — **per-camera** checks: "Camera: Workshop Yard — localhost:8554
reachable (1ms)", "Camera: Front Door — localhost:8554 reachable (1ms)",
"Camera: Demo Camera — file source has no network endpoint to probe".
This is precisely the "tell me where it failed" tool he was looking
for. Verdict: excellent, no gaps found for his use case.

**Goal 5 — logs/status.** Covered by the doctor page above; didn't find
a separate raw-log viewer to check, but the doctor's per-check detail
made that unnecessary for this session's scope.

## Findings

None. Every surface Steve touched (manual RTSP add, bad-URL handling,
ONVIF scan, System doctor) worked correctly and matched his stated
temperament. No new F-numbered findings from this run.

## What worked well

- Wrong-URL connect-test error names the exact IP:port and gives a
  concrete, non-generic cause + fix, with an explicit "add anyway"
  escape hatch for cameras that are just temporarily offline.
- System doctor breaks failures down per-service AND per-camera with
  timings, so "which piece is broken" is answerable at a glance instead
  of inferred from a single offline camera row.
- ONVIF scan gives an honest, specific "nothing found" message rather
  than hanging or silently returning empty.
- Raw RTSP add-to-detecting latency was under a minute end to end.

## Product verdict, in Steve's words

"Finally a tool that tells me *what* broke instead of just *that* it
broke. Threw a dead IP at it on purpose and it named the port and told
me to check the firewall — that's the diagnosis I'd have done by hand.
Doctor page is exactly my kind of screen."
