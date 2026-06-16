# Findings

Curated view of mapped Frigate PRs. Newest batch first. Raw rows: `ledger.jsonl`.
Status: HAVE · PARTIAL · MISSING · VERIFY · FIXED · N/A. Priority P0–P3. Effort S/M/L/XL.

Coverage so far: PRs **23488 → 22984** triaged (120), newest of 4058 merged.

---

## Batch 1 (PRs 23488–23304)

### P0 — Security

#### [#23478] ffmpeg export args: blocklist → allowlist · `record` · PARTIAL → issue
Frigate's blocklist on user-supplied ffmpeg export args was bypassable (stream-specifier
filters, scheme-less protocols, `tee`/preset/`-/option` file access), enabling arbitrary file
read/write + SSRF. They switched to a structural **allowlist** of encoder flags + safe filters.
**Nurby:** `conversation_clip.py` and `agent/analyzer.py` pass `Recording.file_path` into ffmpeg
through a permissive `_resolve_path` fallback, and there is no ffmpeg-arg allowlist. SSRF was a
deliberate skip (overnight-review memory). **Action:** allowlist ffmpeg flags; force file paths
through `shared/paths` containment; block private-network SSRF on `http` stream/snapshot URLs.
**P0 · M.** Partly addressed by the stream-URL fix below; remainder tracked as a GitHub issue.

### P1 — Reliability

#### [#23352] Stream-URL scheme validation (+rtsps://) · `config` · ✅ FIXED this batch
Frigate added `rtsps://` to camera URL validation. Investigating revealed nurby had **no
stream-URL scheme validation at all**, so `file:///etc/passwd` and `http://127.0.0.1/...` were
accepted → arbitrary file read + SSRF. **Shipped:** `validate_stream_url()` in
`shared/schemas.py` — a stream-type-aware scheme allowlist (rtsp/rtsps for rtsp+webcam,
http/https for mjpeg/snapshot/hls), passing through path types (usb/file), rejecting
`file://`/`gopher://`/`dict://` and cross-type schemes. 14/14 checks pass. Tests:
`tests/test_stream_url_validation.py`.

#### [#23475] PTZ autotracking crash on non-finite distance · `ptz` · VERIFY → issue
Frigate's autotracking divided by a tracker distance that could be NaN/inf and crashed. Nurby's
**object** tracker (`tracker.py`) is already guarded, **but** nurby has a PTZ smart-track
subsystem (`ptz_smart_track_*`, `schemas.py:141`) whose move math (`gain*distance`, deadzone,
max_speed) was not inspected. **Action:** audit the smart-track controller; clamp + skip move on
non-finite pan/tilt/zoom deltas. **P1 · S.**

### P2 — Feature parity

#### [#23378, #23383, #23359, #23307] Motion search + review items · `review` · MISSING → issue
Frigate has a **review** subsystem (alerts/detections as "review items") and **motion search**
(scrub a time range by where/when motion occurred). Nurby has Alerts/Detections tabs and a
timeline but no motion-search/scrubbing. See `initiatives/motion-search-and-review.md`. **P2 · L.**

#### [#23387] Hide camera from review feed · `review` · PARTIAL → issue
Second visibility flag: hide a camera from the review/alerts feed independently of the dashboard
hide; recording continues. Nurby's camera-wall hide (commit `b870614`) only covers the dashboard.
**Action:** per-camera `exclude_from_review` flag. **P2 · S.**

### P2/P3 — Smaller items (backlog, not separately filed)

- **[#23482] Lazy GenAI provider init** · `genai` · VERIFY · P2/S — Frigate tolerates a GenAI
  provider that fails on initial load and retries lazily. Check `vlm.py`: does a bad provider key
  crash the perception worker at startup or degrade gracefully?
- **[#23365] ONVIF PasswordText auth** · `discovery` · VERIFY · P3/S — support both PasswordText
  and PasswordDigest WS-Security in `discovery/onvif.py`.
- **[#23339] Clone camera settings** · `api` · MISSING · P3/S — duplicate a camera's config
  (minus stream_url/credentials) to speed multi-camera setup.
- **[#23453] Recording keyframe analysis in probe** · `record` · MISSING · P3/M — ffprobe-based
  keyframe-interval readout; warn on long GOP / smart-codec recordings.
- **[#23393] ffmpeg 8 by default** · `deps` · VERIFY · P3/S — check the ffmpeg version baked into
  nurby images; v8 brings decode/hwaccel improvements.
- **[#23310] MP4 export chapters** · `record` · MISSING · P3/S — chapter markers on export.

### Recorded as HAVE / N/A (checked, no action)

- **[#23457] Chat tool calling + prompt fix** — HAVE. Our agent loop already re-includes tool
  calls each turn, jsonschema-validates, and falls back gracefully on all providers.
- **[#23326] Restore runtime state on restart** — HAVE. DB-driven config persists toggles.
- **[#23445] ZMQ subscription narrowing** — N/A. Nurby uses Redis streams + DB poll, not ZMQ.
- **[#23306] Profiles fixes**, **[#23404] reference config** — N/A. Tied to YAML provisioning.
- **[#23324] classifier trainset script**, **[#23476] API auth docs spec** — N/A / HAVE.

---

## Batch 2 (PRs 23295–23172)

### P1 — Security (architectural — issue filed, NOT auto-fixed)

#### [#23256, #23294] Per-user camera access control · `comms`/`review` · VULNERABLE → issue
Frigate filters **outbound WebSocket broadcasts** and **review/list results** by each recipient's
camera access. Nurby does neither on the main app surface:
- `services/api/ws.py` (`_deliver_local`/`broadcast`/`relay_loop`) pushes every event/detection to
  every connected client. Guardian alerts also broadcast to all.
- List endpoints (`events.py`, `recordings.py`, `observations.py`, `cameras.py`) return **all**
  cameras' data to any authenticated user. Only the Guardian surface is scoped.
This is likely **by design for the single-owner V1**, but it blocks any multi-user/restricted-view
feature and is a data-leak the moment a non-admin account exists. **Deliberately not auto-fixed**:
it needs a user→camera ACL model; merging a half-baked one unsupervised could break the app. See
`initiatives/camera-access-control.md`. **P1 · L.**

### P1 — Reliability

#### [#23172] Filesystem TOCTOU / transient-stat crashes · `record` · ✅ FIXED this batch
Frigate hardened `os.stat`/`exists`+`getsize` flows that crash on transient FS errors
(`Errno 121 Remote I/O`) on network mounts. Nurby had the same unguarded idiom in
`guardian/video.py:44,62` and `conversation_clip.py:158`. **Shipped:** `shared.paths.safe_getsize()`
(guarded, TOCTOU-free) + swapped 4 call sites (also `ingestion/stream.py` recording save now
persists even if the size stat hiccups). Tests: `tests/test_safe_getsize.py`. **P1 · S.**

### P2 — Feature

#### [#23281] Support reasoning / "thinking" models · `genai` · PARTIAL → issue
Frigate added dynamic-thinking-model support. Nurby's `vlm.py`/agent call Claude + OpenAI (which
expose thinking budgets) but don't set thinking params or strip reasoning tokens from outputs.
**Action:** handle thinking/reasoning params + token accounting for reasoning models. **P2 · M.**

### P3 / HAVE / N/A (checked, recorded)

- **[#23261] nginx admin cache leak** — SAFE (no nginx proxy_cache). But the **new** dashboard
  `widget_proxy.py` cache is keyed by `widget_id` only, not user → minor cross-user reuse. Filed P3.
- **[#23265] Credential redaction** — SAFE. Camera creds are Fernet-stored, separate from
  `stream_url`; the authed URL is never logged.
- **[#23206] Semantic chat query** — HAVE. Agent already does pgvector semantic search.
- **[#23188] OpenVINO multi-GPU**, **[#23190] Intel stats**, **[#23251] go2rtc pane**,
  **[#23287/76/70] debug replay**, **[#23264] move_preview_frames** — N/A (no OpenVINO/Intel/go2rtc;
  Nurby uses MediaMTX).
- Deferred (opaque "Misc fixes"/UI tweaks, revisit if a theme needs them): #23295, #23279, #23258,
  #23238, #23235, #23217, #23201, #23186, #23177, plus settings/UI tweaks.

---

## Batch 3 (PRs 23164–22984)

### P1 — Reliability

#### [#22984] No timeout on async ffmpeg subprocesses · `util` · ✅ FIXED this batch
Frigate enforced a python-level timeout on probe subprocesses (a stalled stream hangs the worker
forever). Nurby's `agent/analyzer.py` (frame extract) and `conversation_clip._run_ffmpeg` awaited
`communicate()` with **no timeout**. **Shipped:** wrapped both in `asyncio.wait_for` + kill-and-reap
on timeout (analyzer 20s, clip 120s); clip returns sentinel `124`. `webcam_bridge` left long-lived
(it's a supervised restart loop). Tests: `tests/test_ffmpeg_timeout.py`. (ffprobe itself is unused.)

### P1 — Security (reinforces existing issue #40)

#### [#23164, #22987] Cross-camera media safety / camera access fixes · `api` · VULNERABLE
More evidence for the per-user camera ACL gap: media-serving + access enforcement are not
per-user scoped. Folded into `initiatives/camera-access-control.md` (issue #40). No new issue.

### Accuracy — verified clean (important non-finding)

#### [#23123] BGR vs RGB to the face detector · `data_processing` · HAVE
Frigate was silently feeding RGB to a BGR-trained detector (degraded confidence). **Audited
nurby and it is correct**: InsightFace gets BGR (`faces.py:74`), CLIP converts BGR→RGB
(`vlm_gate.py:145`), EasyOCR uses grayscale (`plates.py:79`), YOLO gets BGR (ultralytics handles).
No change — verified rather than assumed.

### P3 backlog (not separately filed)

- **[#23096] Ollama Cloud `api_key` auth** — add optional bearer key to the Ollama VLM provider.
- **[#22996] Min-length nudge for VLM scene captions** — push the VLM toward detailed descriptions.
- **[#23052, #23310] MP4 export chapter markers**, **[#23034] download incident as evidence zip**
  (VERIFY nurby evidence export), **[#22993] face-recognition perf** — revisit in topical passes.
- N/A: #23118/#23040 ROCm, #23108 Intel stats, #23099 debug-replay jobs.
