# Findings

Curated view of mapped Frigate PRs. Newest batch first. Raw rows: `ledger.jsonl`.
Status: HAVE · PARTIAL · MISSING · VERIFY · FIXED · N/A. Priority P0–P3. Effort S/M/L/XL.

Coverage so far: PRs **23488 → 23304** triaged (40), newest of 4058 merged.

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
