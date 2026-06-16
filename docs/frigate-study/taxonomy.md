# Taxonomy: Frigate subsystem → Nurby owner

Classify each PR by the Frigate package its changed files touch, then map to the Nurby
subsystem that would own the equivalent. Used by the triage stage.

| Frigate area (`frigate/…` or `web/`) | What it does | Nurby owner | Notes |
|---|---|---|---|
| `detectors/` | pluggable detector backends (Coral/TensorRT/OpenVINO/ONNX) | `services/perception/detector.py` | Frigate ahead: plugin arch + HW accel |
| `object_detection/` | detection loop, region cropping, decimation | `services/perception/pipeline.py` | check ROI/decimation parity |
| `track/` | object tracking (Norfair) | `services/perception/tracker.py` | Frigate ahead: Kalman/Norfair vs centroid |
| `motion/` | motion detection + masks | `services/ingestion/stream.py` | check mask math, tuning |
| `record/` | segment recording, cache, export | `services/ingestion/stream.py` + `retention.py` | export hardening, segment cache |
| `review/` | review items (alerts/detections grouping) | `services/events/` + Alerts page | "review item" concept worth studying |
| `output/` | birdseye, restream, jsmpeg/webrtc | `services/ingestion/mediamtx_mux.py` | birdseye missing |
| `ptz/` | PTZ control + autotracking | `services/discovery/onvif.py` | autotracking likely missing |
| `video/` | ffmpeg capture, hwaccel decode | `services/ingestion/stream.py` | hwaccel decode missing |
| `ffmpeg_presets.py` | ffmpeg arg presets | (inline in stream.py) | adopt preset structure |
| `genai/` | GenAI descriptions | `services/perception/vlm*.py` | Nurby ahead |
| `embeddings/` | semantic search embeddings | `services/search/embeddings.py` | parity-ish |
| `data_processing/` | face/LPR/bird classification | `services/perception/faces.py`, `plates.py` | parity-ish |
| `config/` | config schema + validation | `shared/models.py`, `app_settings.py` | DB-driven vs YAML |
| `comms/` | mqtt/ws dispatcher, runtime state | API WS + Redis streams | runtime-state pattern |
| `events/`, `timeline.py` | event lifecycle | `services/events/engine.py` | parity-ish |
| `api/` | REST API | `services/api/` | parity-ish |
| `stats/` | system/inference stats | (minimal) | observability gap |
| `db/`, `migrations/` | SQLite + migrations | Postgres + alembic | architecture differs |
| `web/` | React frontend | `frontend/` | per-feature |
| `util/`, `service_manager/`, `jobs/` | infra | `shared/`, service runners | case by case |

## Type detection (from title + files)

- **security** — title/body mentions bypass, SSRF, sanitize, allowlist/blocklist, auth, token.
- **accuracy** — detection/tracking/recognition correctness, thresholds, false-positive.
- **performance** — optimize, latency, memory, decode, cache, endpoint speed.
- **reliability** — crash, restart, reconnect, restore, watchdog, race.
- **feature** — "Add …", new capability.
- **bugfix** — "Fix …" not covered above.
- **skip buckets** — `deps` (dependency upgrade), `docs`, `i18n` (locale/translation),
  `ci` (github_actions), `hass` (home-assistant addon/integration), pure UI styling tweaks.

## N/A by default for Nurby

Home Assistant addon/integration, Coral-specific code paths (unless we adopt Coral),
Frigate+ model marketplace, anything tied to Frigate's SQLite/config.yml provisioning model
that Nurby's DB-driven config already supersedes.
