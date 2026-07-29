# Frigate Docs Parity — Findings

Every feature Frigate documents, mapped to Nurby state. Legend:
**HAVE** parity/ahead · **PARTIAL** exists but narrower · **MISSING** absent · **N/A** excluded by architecture.

Confidence: HAVE/MISSING calls are grep-verified against `services/`+`shared/`. A few PARTIALs are
marked *(verify)* where the boundary is fuzzy and worth a code read before acting.

---

## 1. Cameras & Ingestion

| Frigate (doc) | Nurby | Notes |
|---|---|---|
| Add-camera wizard: name → probe/snapshot → stream cfg → validation (`cameras.md`) | PARTIAL | Nurby has camera add + onboarding, but no guided probe-then-validate wizard with per-step stream testing. |
| ONVIF discovery + PTZ (`cameras.md`, `autotracking.md`) | HAVE | `discovery/onvif.py`, PTZ present. |
| PTZ autotracking (`autotracking.md`) | **HAVE, ahead** | `perception/ptz_tracker.py` is identity-gated (`ptz_smart_track_require_face`, targets/ignore/priority/no-go) — richer than Frigate's motion-only autotrack. |
| Camera groups / group dashboards (`cameras.md`, `usage/live.md`) | PARTIAL | Nurby has dashboards + camera wall widgets, but not Frigate's named camera-group primitive with per-group live layout + streaming settings. |
| Two-way audio / talk (`cameras.md`, `live.md`, `restream.md`) | MISSING | Only 3 stray refs; streaming is WHEP-out. No backchannel/talk path. |
| go2rtc restream (`go2rtc.md`, `restream.md`) | N/A | Nurby uses MediaMTX, not go2rtc. |
| Birdseye mosaic stream (`birdseye.md`) | MISSING | No combined-view mosaic. Niche. |
| Camera-vendor setup guides (`camera_specific.md`) | N/A | Docs-only (Reolink/Hikvision/Dahua/Wyze…). |

## 2. Detection / Perception

| Frigate | Nurby | Notes |
|---|---|---|
| Object detectors: Coral/Hailo/OpenVINO/ONNX/ROCm/CPU (`object_detectors.md`) | N/A (behind) | Nurby is CPU YOLO + model-agnostic VLM. No detector-plugin arch / hardware accel. Deliberate; see hardware note below. |
| Object filters: min_score, threshold, area, proportions (`object_filters.md`) | PARTIAL | Confidence gating exists; area/aspect-ratio shape filters not fully surfaced. |
| Masks: motion mask + object-filter mask (`masks.md`) | PARTIAL | Motion + `privacy_zones.py` present; object-filter masks (per-label region exclusion) less complete. |
| Motion tuning: threshold, contour_area, lightning_threshold, improve_contrast (`motion_detection.md`) | PARTIAL | Threshold + zones present; `lightning_threshold` and `improve_contrast` **missing**. |
| Stationary objects (`stationary_objects.md`) | PARTIAL | R2 stationary suppression exists; no explicit tunable stationary lifecycle. |
| Zones: loitering, inertia, speed estimation, speed threshold (`zones.md`) | PARTIAL | Loitering trigger HAVE; speed estimation PARTIAL (traffic-monitoring); **zone inertia missing**. |
| Face recognition (`face_recognition.md`) | HAVE | InsightFace, training set, recent-recognitions. |
| License plate recognition (`license_plate_recognition.md`) | HAVE | EasyOCR pipeline, dedicated-LPR concepts present. |
| Audio detection + labels (`audio_detectors.md`) | HAVE | Audio events pipeline. |
| Audio transcription (`audio_detectors.md`) | HAVE | faster-whisper STT. |
| Custom classification — object & state classifiers you train (`custom_classification/*`) | MISSING | No user-trainable custom classifier (e.g. "is the gate open"). |
| Bird classification (`bird_classification.md`) | MISSING | Niche. |
| Semantic search (`semantic_search.md`) | HAVE | pgvector + CLIP. |
| **Semantic-search Triggers** (`semantic_search.md`, `explore.md`) | MISSING | Reference image/description → fire notification when a tracked object matches above a threshold. Documented Frigate feature; fits Nurby's pgvector cleanly. |

## 3. GenAI / LLM

| Frigate | Nurby | Notes |
|---|---|---|
| GenAI providers (Ollama/OpenAI/Gemini/Azure, local+cloud, instruct vs thinking) (`genai/config.md`) | HAVE | Model-agnostic provider layer. Thinking-model params PARTIAL (tracked separately). |
| GenAI object descriptions (`genai/objects.md`) | HAVE | VLM enrichment + per-camera prompts. |
| GenAI review summaries + preferred language (`genai/review_summaries.md`) | HAVE | Digest/summaries subsystem. |
| Review **Reports** (scheduled/programmatic AI reports) (`review_summaries.md`) | PARTIAL | `routes/reports.py` exists; verify parity with Frigate's report-request API + cadence. |

## 4. Review / Events

| Frigate | Nurby | Notes |
|---|---|---|
| Review items: alerts vs detections (`review.md`, `usage/review.md`) | HAVE | Alerts/Detections tabs. |
| Restrict alerts/detections to labels (`review.md`) | PARTIAL *(verify)* | Rule labels exist; per-camera alert-vs-detection label split unclear. |
| Exclude camera from alerts/detections independently (`review.md`) | PARTIAL | `exclude_from_review`-style flag partly present (6 hits); confirm it's independent of dashboard-hide. |
| Restrict review items to zones (`review.md`, `zones.md`) | PARTIAL | Zone-scoped rules exist; review-item zone restriction less explicit. |
| **Reviewing Motion — Motion Previews + Motion Search** (`usage/review.md`, `review.md`) | **HAVE** (corrected 2026-07-29) | `MotionSample` table (1 row/cam/sec from the existing motion pipeline) + `GET /cameras/{id}/motion` server-side `date_bin` bucketing (`services/api/motion_query.py`, comment cites Frigate #23383) + `/cameras/{id}/activity-strip` + frontend `MotionHeatstrip`/`ActivityStrip`/`ActivityTimeline` with clickable seek. Behind default-off `motion_series_enabled`. Only genuine remainder: a dedicated *motion-only review tab* framing. |
| Mark items reviewed / bulk actions (`usage/review.md`) | HAVE | Bulk select + ack present. |

## 5. Recording / Storage / Export

| Frigate | Nurby | Notes |
|---|---|---|
| Recording retention **modes**: continuous / motion / object (`record.md`) | **HAVE** (corrected 2026-07-29) | `Camera.recording_mode` = off/always/on_motion/on_object/clip + `retention_mode` = none/time/size. Per-mode retention-days granularity is thinner than Frigate but the modes exist. |
| **Pre-capture / post-capture** buffer around events (`record.md`) | MISSING ✓ | No `pre_capture`/`post_capture` fields anywhere. Genuine gap. |
| Export recordings + custom-FFmpeg export (`record.md`, `usage/exports.md`) | HAVE | Export + conversation-clip pipeline. |
| **Cases** — bundle related events/clips into a shareable evidence case (`usage/exports.md`) | PARTIAL | Nurby has incidents + evidence cards + shares, but no multi-incident "case" container for export/share. |
| Snapshots: options, retention, frame selection, rendering (`snapshots.md`) | PARTIAL | Snapshots + thumbnails present; frame-selection + snapshot-retention knobs thinner. |
| Storage usage accounting (`record.md`) | PARTIAL | Disk stats present; not Frigate's per-mode usage breakdown. |
| Sync media with disk (`record.md`) | HAVE | DB-driven retention/reconcile. |

## 6. Live / UI

| Frigate | Nurby | Notes |
|---|---|---|
| Live view: WebRTC / MSE / jsmpeg tiers (`live.md`, `usage/live.md`) | HAVE | WHEP via MediaMTX. |
| History timeline: scrubbing + previews + calendar (`usage/history.md`) | HAVE | Recent scrubber work (clickable seek + activity heatmap). |
| Explore / semantic-search UI (`usage/explore.md`) | HAVE | Search UI. |
| On-demand recording + snapshot from live (`usage/live.md`) | PARTIAL *(verify)* | Snapshot yes; manual on-demand record toggle unclear. |
| PWA install (`pwa.md`) | MISSING *(verify)* | Next.js app; installable-PWA manifest/service-worker not confirmed. |

## 7. Auth / Multi-user

| Frigate | Nurby | Notes |
|---|---|---|
| Authentication + JWT bearer + onboarding (`authentication.md`) | HAVE | `shared/auth.py`. |
| Login failure rate limiting, session length, JWT secret (`authentication.md`) | PARTIAL *(verify)* | Confirm rate-limit + session-length knobs. |
| **User roles + custom roles + per-camera access** (`authentication.md`) | **HAVE** (corrected 2026-07-29) | Roles admin/viewer/guardian + `UserCameraAccess` table + `shared/camera_access.allowed_camera_ids` (ALL for admins, explicit allowlist otherwise), enforced across events/recordings/observations/cameras/incidents/shares/digest/guardian/users. Remaining: fully-custom named roles + WS-fanout filtering audit. |
| Proxy header auth / role mapping (`authentication.md`) | N/A | Nurby is pure bearer-JWT, no reverse-proxy header trust. |

## 8. Integrations

| Frigate | Nurby | Notes |
|---|---|---|
| HTTP API (`integrations/api.md`) | HAVE | FastAPI + OpenAPI. |
| Notifications / web-push (`notifications.md`) | HAVE | FCM mobile push (`shared/push.py`) + Telegram. |
| Webhooks | HAVE, ahead | `webhook_subscriptions.py` — Frigate has no first-class webhook subscriptions. |
| **MQTT** (`integrations/mqtt.md`) | MISSING | Large home-automation surface: state topics, set/state per camera, events/reviews/stats. |
| **Home Assistant** integration (`integrations/home-assistant.md`) | MISSING | The single biggest ecosystem driver for Frigate's audience. |
| **HomeKit** (via go2rtc) (`integrations/homekit.md`) | MISSING | Tied to go2rtc; N/A-ish for MediaMTX. |
| **Prometheus metrics** (`configuration/metrics.md`) | MISSING | `admin_stats.py` exists but no `/metrics` Prometheus endpoint or Grafana dashboard. |
| MCP server | HAVE, ahead | `services/mcp/` — Nurby-only. |

## 9. Config system

| Frigate | Nurby | Notes |
|---|---|---|
| YAML config + Settings UI + schema validation (`config.md`, `advanced/system.md`) | N/A | Nurby config is DB-driven, not a YAML file. |
| Config overrides: global vs per-camera, lists-replace/maps-merge (`config_overrides.md`) | PARTIAL | Per-camera settings exist; not a formal override-resolution model. |
| **Profiles: Home/Away, schedulable, arm/disarm presets** (`profiles.md`) | MISSING | No mode/profile switching (arm/disarm, home/away) toggling rules+recording+detection en masse. High prosumer value. |

## 10. Hardware acceleration — all N/A (deliberate)

`object_detectors.md`, `hardware_acceleration_video.md`, `hardware_acceleration_enrichments.md`,
`ffmpeg_presets.md`, Coral/Hailo/OpenVINO/ROCm/Jetson/Rockchip/Apple-Silicon/TensorRT.

Nurby is CPU + model-agnostic VLM by design. This is the one axis where Frigate is structurally
ahead, and chasing it means a detector-plugin architecture. Out of scope unless perf forces it.

`tls.md` also N/A (deploy-layer, handled at ingress).

---

## What to implement — ranked

> **Revised 2026-07-29 after full code verification.** The original Tier-1 assumed motion-search,
> per-user camera access, and recording modes were missing. They are **all built**. The list below
> is only the gaps that survived a real code read.

Ordered by (value to Nurby's prosumer V2 target) × (fit with existing architecture) ÷ effort.

### Tier 1 — verified genuine gaps

1. **Semantic-search Triggers** — mirror `semantic_search.md` "Triggers" + `explore.md`. Add a new
   rule trigger type (e.g. `semantic_match`) alongside the existing catalog in
   `services/events/engine.py::_match_trigger`: a reference image/description → embedding, fire when
   a tracked object's embedding is within a similarity threshold. We already have pgvector
   embeddings, the trigger dispatch, and notifications, so this is mostly a new trigger case + a
   reference-store table + small UI. **Best architectural fit of the three.** **P2 · M.**

2. **Pre-capture / post-capture recording roll** — mirror `record.md`. Buffer N seconds before and
   after a tracked object so clips include lead-in/lead-out. No `pre_capture`/`post_capture` today.
   Touches the ingestion recording path. **P2 · M.**

3. **Profiles / Home-Away modes** — mirror `profiles.md`. Schedulable presets that flip rules +
   recording + detection together (arm/disarm). No mode/profile primitive exists today (rules are
   always-on with cooldowns). Strong prosumer-family value. **P2 · M.**

### Already built (do not rebuild) — corrected

- Motion Search + Previews · Per-user camera access + roles · Recording modes (off/always/on_motion/
  on_object/clip) + retention (time/size). See the matrix above for the exact code locations.

### Tier 2 — smaller parity wins

6. **Exclude-camera-from-alerts/detections** independent of dashboard-hide (`review.md`). **P3 · S.**
7. **Object shape filters** — area + aspect-ratio parity (`object_filters.md`). **P3 · S.**
8. **Cases** — bundle multiple incidents/clips into one shareable evidence case (`exports.md`). **P3 · M.**
9. **Prometheus `/metrics` endpoint + Grafana dashboard** (`metrics.md`). **P3 · M.**
10. **Motion tuning knobs** — `lightning_threshold` + `improve_contrast` + zone inertia
    (`motion_detection.md`, `zones.md`). **P3 · S.**

### Tier 3 — ecosystem integrations (bigger bets, audience-dependent)

11. **MQTT integration** (`integrations/mqtt.md`) — unlocks the home-automation crowd.
12. **Home Assistant integration** (`integrations/home-assistant.md`) — Frigate's #1 adoption driver.
13. **Two-way audio / talk** (`live.md`, `restream.md`).
14. **Custom classification** — user-trainable object/state classifiers (`custom_classification/*`).
15. **Birdseye mosaic** (`birdseye.md`).

### Do not chase (N/A by architecture)

Hardware detectors & video accel, go2rtc/HomeKit, YAML config + Settings-UI-for-YAML, TLS at app
layer, camera-vendor setup guides, Frigate+ model marketplace.

---

## The "match one-to-one" answer

After verification, the docs worth mirroring for *new* work, in priority order:

1. `configuration/semantic_search.md` (Triggers) → **semantic triggers**.
2. `configuration/record.md` (Pre/post capture section) → **pre/post-capture roll**.
3. `configuration/profiles.md` → **home/away profiles**.

Already matched (don't re-mirror): `review.md`/`usage/review.md` (motion search), `authentication.md`
(roles + camera access), the recording-modes half of `record.md`.

Everything above the hardware line is reachable in Nurby's current architecture. Everything at or
below it (detectors, accel, go2rtc, YAML) is a deliberate non-goal.
