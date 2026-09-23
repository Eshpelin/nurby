# Camera content health: frozen / obscured / tampered views

**Issue:** #212 · **Status:** detection core + rule triggers shipped (global opt-in);
per-camera toggles deferred (see below). Feeds the coverage contract (#194).

## Why

`camera_offline` only catches dead connections. The failures that matter most
keep a normal-looking stream alive while coverage is silently gone: a frozen
decoder (socket up, frames stop changing), a covered or defocused lens, or a
camera turned to face a wall. A recorded stretch behind such a view must not
later be summarized as a quiet period.

## Detection

`services/ingestion/content_health.py` `ContentHealthDetector` runs off
already-decoded frames (no extra decode pass), sampled about once a second in
the ingestion loop:

- **Frozen decoder** - an *identical* perceptual hash (8x8 average-hash)
  sustained for `freeze_seconds` (default 180s). A live frame is never
  byte-identical to the previous one, so this is unambiguous, and a merely
  quiet scene, whose hash keeps changing, never trips.
- **Obscured / tampered** - grayscale variance below `obscure_variance` for
  `obscure_seconds`: a covered or wall-facing lens is near-uniform.

Each path is independently toggleable (`detect_freeze`, `detect_obscure`), and
recovery requires a sustained clear stretch (`recover_seconds`) so the state
never flaps.

## Signalling

On a confirmed transition, ingestion publishes a `degraded` / `recovered`
edge on the same `nurby:camera_status` stream used for offline/online, and
writes a `camera_status_logs` row, **without changing the camera's primary
status** (a frozen camera is still streaming, so recording/live are left
alone). The perception rule engine matches these to two new rule triggers:

- `camera_degraded` - fires on a `degraded` edge.
- `camera_recovered` - fires on `recovered`.

These are distinct from `camera_offline`/`camera_online`; an offline event
never fires a degraded rule and vice-versa (`services/events/engine.py`).

## Enabling

Enabled when a camera's own `content_health_enabled` flag is on **or** the
global `content_health_enabled` app setting is on; read by the ingestion
worker on a 60s cache. Off by default so it ships safely. Each detection path
is independently toggleable per camera via `freeze_detection_enabled` and
`obscuration_detection_enabled` (both default on); flipping one rebuilds the
detector on the next cache refresh.

## Coverage

Degraded intervals land in `camera_status_logs` as offline-style rows, which
the coverage contract (#194, `services/perception/coverage.py`) reads, so a
degraded stretch surfaces in Home/recaps/Ask and cannot be called quiet.

## Deferred

- **Periodic VLM "is this the expected scene?" check** for tamper/scene-change
  against a learned baseline (`services/perception/baseline.py`), respecting
  cost controls (hourly, skip when the CLIP gate would call the frame boring).
  The cheap frozen/obscured detectors ship first.

Source: `services/ingestion/content_health.py`, wiring in
`services/ingestion/stream.py`, triggers in `services/events/engine.py`,
tests `tests/test_content_health.py` + `tests/test_camera_status_trigger.py`.
