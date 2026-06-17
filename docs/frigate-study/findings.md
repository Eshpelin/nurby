# Findings

Curated view of mapped Frigate PRs. Newest batch first. Raw rows: `ledger.jsonl`.
Status: HAVE · PARTIAL · MISSING · VERIFY · FIXED · N/A. Priority P0–P3. Effort S/M/L/XL.

Coverage so far: PRs **23488 → 19428** triaged (880, ~22% of 4058 merged), newest-first.

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

---

## Batch 4 (PRs 22980–22814) — coverage batch, no code change

Low yield: dominated by Intel/OpenVINO/ROCm, dependency bumps, docs, i18n, and frontend tweaks
(all N/A or skip for nurby). **No fix forced** — none of the substantive items was a clean,
high-confidence change safe to merge unattended. Worth a later look (backlog / VERIFY):

- **[#22887] Manual events caught by motion config** · `record` · P3/S — ensure manually- or
  API-triggered events bypass `recording_mode=on_motion` gating.
- **[#22971] Stream probe fallback** · `video` · P3/M — graceful fallback/reconnect when the
  primary stream probe fails.
- **[#22818] UTF-8 ONVIF preset names** · `ptz` · P3/S — verify `discovery/onvif.py` decodes
  non-ASCII preset names correctly.
- **[#22880] Deferred enrichment processor** · `data_processing` · P3/M — move expensive
  enrichment off the hot path (compare to nurby `vlm_queue`/enrichment workers).
- **[#22915/#22867] Export progress + improvements**, **[#22963] camera-wizard polish** — UI passes.
- **[#22894] python-multipart bump** — check nurby's pinned version for the same CVE separately.

---

## Batch 5 (PRs 22799–22673) — coverage batch, no code change

Yield still low (genai refactors, Intel/MemryX/go2rtc/llama.cpp, dep bumps, docs, UI tweaks).
Two checks worth recording:

- **[#22689] numpy box coords not JSON-serializable** · `data_processing` · **HAVE** — audited
  and nurby is clean: every numpy value is cast to native python at the vision boundary
  (`detector.py:235-256`, `plates.py:171-181`, `faces.py:86-90`), and `ws.py` uses
  `json.dumps(default=str)` as a net. Verified, not assumed.
- **[#22710] Role-based auth on WS message handler** · `comms` · VULNERABLE — reinforces the
  per-user camera ACL gap; folded into issue #40 (no new issue).

Backlog / VERIFY: **[#22698]** DST-safe time windows (digest/preview tz math), **[#22732]**
zone/mask editor UX, **[#22787/#22733/#22683]** frontend dep CVE audit (lodash/path-to-regexp),
**[#22673]** secondary-pipeline cadence, **[#22685]** ONNX warm-up (only matters once GPU lands).
N/A: MemryX, go2rtc, llama.cpp, MQTT, Intel stats.

---

## Batch 6 (PRs 22664–22540) — coverage batch, no code change

Region heavy with mypy/typing, hardware-accel (Axera/ROCm/CUDA/DEIMv2/MemryX), deps, i18n, and
genai/UI churn. Two security/reliability items checked:

- **[#22607] Arbitrary ffmpeg read/write** · `record` · PARTIAL → reinforces **issue #35** (P0).
  Same class as #23478. Added a comment to #35 with the concrete approach (path containment +
  `-protocol_whitelist file` on local-file ffmpeg inputs). Not merged unattended — risky without
  testing against real recordings.
- **[#22641] Export deadlock from `preexec_fn`** · `record` · **N/A** — nurby has no `preexec_fn`
  anywhere; it uses `asyncio.create_subprocess_exec`, so it is not exposed to the fork-in-threaded
  -process mutex deadlock.

Backlog/VERIFY: **[#22631]** split nurby's large `stream.py` (maintainability), **[#22557]**
process watchdog/restart-on-hang, **[#22556]** continuous GenAI camera-monitor loop vs nurby
summary/interval, **[#22599]** notification edge cases, **[#22548/#23393]** ffmpeg version in
nurby images.

---

## Batch 7 (PRs 22538–22438) — a real fix + two scrutinized false-positives

A bug-bash region in Frigate. Most of the 22462–22468 cluster is birdseye/GPU (N/A for nurby).

### P1 — Security · ✅ FIXED this batch
**[#22523] Mutating endpoints not admin-gated** · `api`. Found `PATCH /cameras/{id}` (edits
`stream_url`/`username`/`password`/`auth_token`) and `PATCH /providers/{id}` (edits `api_key`)
using `get_current_user`, while their **create/delete siblings already require admin** — a
non-admin could rewrite camera credentials / provider API keys (privilege escalation). **Shipped:**
both PATCH endpoints now `require_admin`; verified via FastAPI route introspection. Remaining
endpoint sweep tracked as issue #46. Cross-camera media/timeline auth (#22522/#22530) → issue #40.

### Scrutinized and rejected (the audit over-flagged; I verified before acting)
- **[#22500] SQL injection** — **HAVE/SAFE**. The flagged `column.ilike(f"%{x}%")` calls bind the
  pattern as a **parameter** (the f-string builds a python string, not SQL). The lone `text(f"…")`
  (`analyzer.py`) uses a hardcoded `WHERE` + bound params. No injection. I did **not** "fix" these
  (would be churn / could break search). LIKE-wildcard widening is handled by `escape_like`.
- **[#22470] PTZ div-by-zero** — **HAVE/SAFE**. `ptz_tracker.py` clamps velocity and guards with
  `max(1, w/h)`; no norm division. This verifies the old issue #36 as a non-issue → **#36 closed**.

### Backlog / VERIFY
- **[#22469]** orphaned snapshot/thumbnail cleanup on camera/event delete · P3.
- **[#22472]** variable-shadowing dropping track updates, **[#22471]** operator-precedence
  always-true, **[#22474]** return-vs-raise, **[#22475]** parse-before-status, **[#22473]** WS leak
  on WebRTC cleanup — generic bug patterns to grep for in nurby · P3 each.
- **[#22537]** shareable timestamped footage deep-link · P3.

---

## Batch 8 (PRs 22426–22295) — one perf fix

### P2 — Performance · ✅ FIXED this batch
**[#22426] Blocking calls stall the async event loop** · `api`. `ollama_deploy.get_ollama_status`
awaited a sync `_get_system_ram_gb()` that shells out to `sysctl` (up to 5s) directly in the
handler — stalling **all** API requests meanwhile. **Shipped:** wrapped in `asyncio.to_thread`.
Remaining blocking file I/O (`persons.upload_face`, `system.trigger_update`, `devices` read) and
unchecked `cv2.imencode` in background workers → issue #48.

### Verified HAVE (checked, no change)
- **[#22331] Missing-preview graceful 404** — nurby media endpoints all use `resolve_inside` +
  `exists` → clean 404. **[#22336] delete cameras**, **[#22323] GenAI embeddings/semantic search** —
  already present.
- **[#22385] Push notifications by camera access**, **[#22347] motion-previews filter** → folded
  into issues #40 and #37 respectively.

### Backlog/VERIFY
- **[#22352]** recordings/calendar API perf (indexing/pagination), **[#22393]** wrong exception
  class in subprocess except, **[#22375]** snapshot query params after event end, **[#22416/#22308]**
  LPR moving-vehicle handling + filter ordering · P3 each. N/A: nginx http/2, go2rtc, RKNN, Intel/GPU deps.

---

## Batch 9 (PRs 22294–22103) — coverage batch, no code change

Feature/deps/version-churn region (0.18 early work, GenAI refactors, zone-editor UX, AXERA/Coral/
birdseye N/A, many dep bumps). Reinforces two existing themes, no new fix:

- **[#22253] Improve motion review + add motion search** → the implementation of issue **#37**
  (motion search initiative). **[#22277/#22255]** motion region/threshold config also there.
- **[#22226] Hide hidden camera alerts** → confirms issue **#38** (a dashboard-hidden camera
  should also drop out of alerts/review).
- **HAVE:** React 19 (#22275), multiple GenAI providers (#22144), GenAI streaming/chat (#22152) —
  nurby already has these.
- Backlog/VERIFY: **[#22254]** auth/login audit logging (nurby has no anonymous login, but an
  auth audit trail is worth considering) · P3.

---

## Batch 10 (PRs 22098–21752) — coverage batch, no code change

0.17-beta era: attributes/secondary-model features (N/A — nurby has no object-attributes or
secondary-classifier concept), Hailo/ROCm/RF-DETR deps (N/A), lots of i18n/docs/misc.

Backlog / VERIFY worth a later look:
- **[#21936] RTSP stream timeout** — nurby uses **5s** (`stream.py:394-395` `stimeout/timeout;5000000`);
  Frigate raised theirs to 15s for slow cameras. A tuning tradeoff (longer = slower offline
  detection), so not changed blind — consider making it configurable · P3.
- **[#21893]** event/incident getting stuck (only checking current clip/snapshot) — compare to
  nurby incident finalization · P3.
- **[#21754]** add a live-snapshot/live-state tool to the chat agent · P3.
- **[#21932]** X-Frame-Time header on snapshot API, **[#21752]** offline-camera placeholder image · P3.
- HAVE: API events as Detections/Alerts by label (#21923 — nurby severity taxonomy R5).

---

## Batch 11 (PRs 21749–21443) — coverage batch, no code change

0.17-beta era: media-sync (N/A), cache-dir cleanup (N/A, nurby is DB-driven), llama.cpp provider
(N/A), GPU/NPU temps (N/A), deps/i18n/docs. Two verified-clean items:

- **[#21676] Cache maintainer crash on stray filename** — N/A. Frigate scans a cache dir and
  `rsplit("@")`-parses `camera@timestamp.mp4`. Nurby has no cache-dir scanner / filename parsing
  (verified: no `listdir`/`scandir`/`glob`/`split("@")` in ingestion/perception); recordings are
  DB-driven. Bug class absent.
- **[#21543] Restrict go2rtc `exec:` sources** — HAVE. The stream-URL scheme allowlist (PR #34)
  already rejects `exec:`/`file:`/non-network schemes for network camera types.

Backlog/VERIFY: **[#21520]** delete-recordings API, **[#21600]** "reviewed" filter correctness,
**[#21668]** time-lapse export · P3. HAVE: LLM chat tool-calling (#21731).

---

## Batch 12 (PRs 21439–21243) — coverage batch, no code change

0.17-beta: object-attributes (N/A), Hailo/vainfo/GPU (N/A), oauth2-proxy/peewee (N/A), i18n/misc.
Two feature themes worth tracking + one verified N/A:

- **[#21299/#21293/#21295] Case management** (PARTIAL) — Frigate groups related events into a
  shareable "case" (bundle clips + metadata, export as evidence). Nurby has incidents + evidence
  cards + reports, but no case container bundling multiple incidents/clips for export/sharing.
  Backlog initiative candidate · P3/L.
- **[#21297] Camera connection-quality indicator** (MISSING) — nurby has online/offline status but
  no per-camera health/quality (drops/bitrate/reconnects) metric · P3/M.
- **[#21335] "consider anonymous user authenticated"** — N/A. Nurby has no auth-disabled/anonymous
  mode; every request needs a JWT.
- Backlog/VERIFY: **[#21250]** two-way/backchannel audio, **[#21322]** export filter UI · P3.

---

## Batch 13 (PRs 21241–21003) — coverage batch, no code change

Heavy 0.17-beta misc + hardware (ROCm/Jetson/Coral/MemryX/OpenVINO = N/A) + docs/i18n.
Security-relevant, all folded into existing issues / backlog:

- **[#21065] Enforce default-admin on API endpoints** + **[#21094] admin exemptions / route
  guards** — strong reinforcement of issue **#46**. Frigate moved to admin-by-default with explicit
  public exemptions (a more robust model than per-endpoint opt-in). Commented on #46.
- **[#21126] Pin cryptography version** — VERIFY nurby's `cryptography` pin (used for Fernet
  camera-secret sealing) is recent/non-vulnerable · P3.
- **[#21110] User-namespaced IndexedDB keys** — reinforces per-user-namespacing (issue #42);
  verify nurby frontend persisted state is user-scoped · P3.
- **[#21194] Authentication improvements** — generic auth hardening; compare to `shared/auth.py` · P3.

---

## Batch 14 (PRs 20989–20790) — coverage batch, no code change

Deep 0.17-beta dev churn: classification/secondary-models (N/A), HLS *frontend* player fixes
(nurby uses MediaMTX, N/A), camera-wizard UI, pluralization/i18n, hardware (MemryX/Jetson/hailo).
No nurby-applicable backend fix.

- **[#20828] Per-camera Review-Summary context** (PARTIAL) — let users add per-camera context to
  GenAI review/digest summaries; nurby has summaries but maybe not per-camera summary context · P3.
- Note: **[#20786] events-summary DST fix** lands at the next batch boundary; folds into the DST
  backlog item (#22698 / digest time-window correctness).

---

## Batch 15 (PRs 20789–20681) — coverage batch, no code change

A DST bug cluster in Frigate (events/recordings/review summaries) prompted a careful nurby audit.

- **[#20786/#20784/#20770] DST in summary windows** — **HAVE (verified, not assumed)**. A sub-agent
  flagged `daily_digest.py:126` (`window_end - timedelta(hours=24)`) as a "critical DST bug." I
  **empirically tested** it in the API image: `timedelta(hours=24) == timedelta(days=1)`, and
  tz-aware datetime arithmetic is wall-clock, so the subtraction keeps local 07:00 and
  `astimezone(utc)` produces the correct boundary (real elapsed 23/24/25h exactly as DST requires).
  `report_scheduler.py` is also textbook-correct. **No fix** — changing it would have been churn and
  a likely regression.
  - Low-confidence VERIFY (behavior-affecting, left for review, not auto-fixed): `daily_digest`
    uses `datetime.now(tz).astimezone()` (system-local tz, not the configured `system_timezone`)
    for its hour check; `persons.py` buckets activity by **UTC** hour (`strftime("%H")`) which may
    want local-hour conversion depending on UI intent.
- HAVE: named zones (#20761 — nurby R3 named areas).
- Backlog/VERIFY: **[#20736]** tag delivery/package detections for the VLM, **[#20715]** show
  no-recording gaps on the timeline, **[#20690/#20704/#20723]** review-summary prompt structure · P3.

---

## Batch 16 (PRs 20677–20533) — coverage batch, no code change

Heavy UI / classification / Intel-NPU / HLS-format / camera-wizard churn (N/A or frontend).
No nurby-applicable backend fix. Backlog/VERIFY:

- **[#20676]** choose which frames feed the VLM review description (frame selection) · P3.
- **[#20620]** camera-wizard stream-validation UX (backend already covered by PR #34 allowlist) · P3.
- **[#20606]** sensible Ollama performance defaults (num_ctx/keep_alive) · P3.

---

## Batch 17 (PRs 20527–20392) — coverage batch, no code change

Mostly UI/genai/Intel/docs. A few backlog items worth noting (no clean unattended-safe backend fix):

- **[#20484] webp snapshots** (storage efficiency) — nurby encodes JPEG thumbnails; webp is ~25-35%
  smaller. Worthwhile storage/bandwidth win but a multi-surface behavior change (write+serve+UI) · P3.
- **[#20446]** mark review/alert items back to unreviewed (toggle ack state) · P3.
- **[#20488]** on-demand snapshot download endpoint · P3.
- **[#20506]** retention-logic edge cases (compare to nurby DB-driven retention) · P3.
- **[#20491/#20483]** input validation: uploaded-image location + face-score range · P3.
- VERIFY: **[#20395]** audio-transcription fix (nurby has faster-whisper STT) — body empty, revisit
  if a theme emerges.

---

## Batch 18 (PRs 20388–20206) — coverage batch, no code change

GenAI review-summary tuning, stationary-object work, RKNN/AMD-GPU (N/A). Two verified HAVE:

- **[#20237] Watchdog enhancements** — HAVE. Verified nurby self-heals stalled streams:
  `stream.py:211` detects frame-read stall and forces reconnect, `:143` exponential backoff,
  `manager.py` restarts workers on config change, `webcam_bridge` supervises ffmpeg. (Also clears
  the earlier #22557 backlog note.)
- **[#20296] Customizable GenAI review prompt** — HAVE (per-camera vlm/summary/digest prompts).
- Backlog/VERIFY: **[#20331]** run object-VLM as a post-processor (compare to `vlm_enrichment_worker`),
  **[#20225]** stationary-tracking edge cases (vs R2 suppression) · P3.

---

## Batch 19 (PRs 20204–20000) — coverage batch, no code change

OpenVINO/CUDA/ROCm/ZMQ-detector/LPR churn (mostly N/A). Notable:

- **[#20024] User roles to limit camera access** — the **reference implementation** for issue #40.
  Roles + allowed-camera set applied across event/export/media/preview/review endpoints + a
  `use-allowed-cameras` frontend hook. Commented on #40 as the build template.
- **[#20099] Invalid LPR-regex crash** — N/A. Verified nurby compiles no user-supplied regex
  (all patterns are constants or `re.escape(user)`); no crash surface.
- Backlog: **[#20190]** small-object detection via region re-detection (accuracy, P2),
  **[#20119]** Prometheus metrics (observability, P3), **[#20101]** per-object speed estimation
  (could complement nurby's traffic features, P3).

---

## Batch 20 (PRs 19998–19777) — coverage batch, no code change (0.17 release window)

Inference-speed/docs updates, Frigate+ model config, CUDA/Intel/degirum (N/A), autotracking
tweaks (our PTZ verified robust), weblate/i18n. One reliability item already HAVE:

- **[#19883] Lower bound on reconnect retry** — HAVE. Nurby reconnect starts at `RECONNECT_DELAY`
  (the floor) and doubles to `RECONNECT_MAX_DELAY` (`stream.py:147/162`).
- Backlog/VERIFY: **[#19930]** best-thumbnail selection, **[#19850]** review/event segmentation
  (vs nurby `incident_idle_seconds` grouping), **[#19873/#19879]** autotracking refinements · P3.

### Milestone: 20% of Frigate's 4058 merged PRs triaged (800 logged).
Pattern so far: the high-value security/reliability fixes clustered in the recent ~8 batches
(23488–22400). The 0.17/0.18 dev region (22xxx–19xxx) is dominated by hardware-accel (Coral/
OpenVINO/ROCm/Hailo/MemryX/Intel/CUDA), classification/secondary-models, go2rtc, i18n, and UI —
nearly all N/A for nurby's CPU + MediaMTX + VLM architecture. 5 fixes shipped, 8 issues open.

---

## Batch 21 (PRs 19776–19615) — coverage batch, no code change

RKNN/Synaptics/AMD/MemryX hardware (N/A), weblate/i18n/docs, HLS frontend. Two verified:

- **[#19657] Catch invalid genai prompt key** — N/A. Nurby passes user prompts verbatim to the
  model (no `str.format` on them) and renders notification templates via regex-sub
  (`events/templates.py`), so unknown tokens don't `KeyError`. No crash surface.
- **[#19709] Camera Health Status** — MISSING (folds into #21297 connection-quality backlog): nurby
  has online/offline + status logs but no detailed per-camera health (fps / frames-received /
  last-frame-time).
- Backlog/VERIFY: **[#19672]** record-on-motion config edge case, **[#19640]** per-viewer
  notification settings (relates to roles/#40) · P3.

---

## Batch 22 (PRs 19614–19428) — coverage batch, no code change

GenAI review-summaries feature wave (nurby HAVE VLM summaries + digest), Apple-Silicon/ZMQ/i965
(N/A), mypy/i18n/docs. Two verified HAVE:

- **[#19555] Content-type for image endpoint** — HAVE. Nurby sets `media_type` explicitly
  (`cameras.py:859` image/jpeg, `body_clusters.py:227` image/jpeg, audio/ogg, video/mp4).
- **[#19567] Camera nickname** — HAVE (name + location_label).
- Backlog/VERIFY: **[#19433]** per-object-type loitering thresholds (nurby has loitering trigger),
  **[#19484]** extra Ollama args (with #20606), **[#19469]** aggregate fps stat (with #20119) · P3.
- Lead for next batch: **[#19426]** "search crashes if query is a number" — will verify nurby search.

---

## Batch 23 (PRs 19426–19134) — coverage batch, no code change

Deep 19xxx dev region: ~90% N/A (hwaccel ROCm/RKNN/Rockchip/Intel/tensorrt, ML
classification/training, weblate i18n, docs, dep bumps, frontend UI/timezone churn).
Three backend bugfixes verified against nurby, all SAFE/N-A:

- **[#19134] IPv6 with IPv4 trusted proxies** (`ipv4_mapped` can be None → `None in network`
  raises) — **N/A**. Nurby has no `get_remote_addr` / trusted-proxy / X-Forwarded-For parsing.
  `ipaddress` only used in `shared/netpolicy.py` for webhook SSRF classification (no membership
  test that can hit None).
- **[#19323] Catch json decode exception** (corrupt `.search_stats.json` crashed embeddings init) —
  **SAFE**. All nurby `json.loads` sites wrap `JSONDecodeError`/`ValueError`
  (`agent/analyzer.py`, `agent/llm.py`, `api/widget_proxy.py`, `api/ws.py`,
  `perception/har_idmap.py`); no persisted stats/cache JSON read at startup.
- **[#19371] Fix not deleting thumbnails** (frigate passed an id where an Event object was
  expected) — **SAFE**. Nurby `ingestion/retention.py` deletes thumbnails by string path
  (`_remove_file(_resolve_path(rec.thumbnail_path))`, lines 346 & 409), no id/object confusion.
- **[#19426] search crashes if query is a number** — **N/A** (frontend TS cast `as string`).
  Nurby `search/query.py:127` coalesces `(query or "").lower().strip()`, FastAPI types the param.
- Backlog/VERIFY (P3, minor): **[#19327]** systemd `CREDENTIALS_DIRECTORY` secrets,
  **[#19207]** ionice for heavy procs, **[#19139]** runtime per-camera GenAI enable/disable.
- Lead for next batch: **[#19110]** "Improve ffmpeg frame handling" — nurby ffmpeg pipeline is a
  known-behind area; verify against `services/ingestion` ffmpeg handling.

## Batch 24 (PRs 19125-18774)

Coverage-only batch, one issue filed. Region remains ~90% N/A (hwaccel, ML classification/LPR, i18n, docs, Frigate multiprocess architecture).

**GAP -> Issue Eshpelin/nurby#65: recordings time-window overlap miss.**
Frigate PR #18897 fixed a review-query overlap bug (old `start_time > after` dropped segments that started before but overlapped the window; fixed to `start_time < before AND (end_time IS NULL OR end_time > after)`). Nurby `services/api/routes/recordings.py` `_filtered_recordings_query()` filters the time window on `started_at` only (`started_at >= from_`), so a clip that started before `from_` but is still running/overlapping is excluded. The same function's *object* sub-filter already uses correct overlap semantics, making the top-level from/to inconsistent. Fix proposed: lower bound on computed `window_end` (coalesce ended_at / started_at+duration). User-facing semantics change (more rows, pagination impact) -> filed as issue, not blind merge.

**Feature backlog (no issue): #18969 Semantic Search Triggers.** Per-camera triggers that fire a notification when a tracked object's thumbnail/description matches reference data above a similarity threshold, managed in UI Settings > Triggers. Nurby has no semantic-search trigger automation. Large future feature tied to the notifications/semantic-search roadmap; noted here for when that subsystem lands.

**Verified N/A (substantive but no nurby analog):**
- #18897 viewer in proxy `VALID_ROLES` header mapping: nurby has no reverse-proxy header auth (#19121 doc tweak X-Forwarded-Groups same area).
- #19110 ffmpeg capture-thread restart refactor (`reset_capture_thread`): Frigate per-camera multiprocess capture loop in `frigate/video.py`; nurby ingestion has no `capture_thread`/`ffmpeg_detect_process`.
- #18885 PIL `verify()` corrupt-thumbnail skip in vision reindex / #19125 reindex tidy: nurby embeds face vectors from recordings, no thumbnail reindex batch.
- #18866 `empty_and_close_queue` manager-proxy guard, #18860 forkserver SIGINT/stop_event, #19105/#19086 ulimit-to-Python: Frigate multiprocess/container infra, nurby is async API.
- #18821 birdseye dynamic add_camera: nurby has no birdseye mosaic.

Minor optional: #18883 ONVIF focus (nurby PTZ has no focus control).

## Batch 25 (PRs 18757-18381)

Coverage-only batch. No issues filed, no fixes merged. ~90% N/A (Frigate multiprocess/hwaccel/ML/LPR/i18n/docs/UI).

**Lead resolved (HAVE):** #18671 Dynamic Management of Cameras (runtime add/remove cameras without restart). Nurby already supports this: cameras are DB-backed, rule edits flush perception caches within ~1s via the rule-invalidation pubsub listener (`services/perception/pipeline.py`), camera availability is tracked by `camera_status_watcher.py`, and there is a 30s passive reload fallback. Frigate's PR exists to solve its monolithic multiprocess restart problem, which Nurby's architecture does not have. Same applies to companion PRs #18353 (Dynamic Config Updates) and #18359 (dynamic masks/zones) — N/A to Nurby's reload model.

**N/A — no proxy-header auth in Nurby:** #18336 (custom header separator for proxy role mapping). Nurby has no `header_map`/`remote-role`/`x-forwarded-role` proxy-auth path, so the comma-vs-pipe separator config is irrelevant.

**Backlog (gap-minor, no issue):**
- #18616 GenAI description generation via API for non-enabled cameras (a `force=true` flag on the regenerate endpoint that bypasses the per-camera genai-enabled check). Nurby's VLM regenerate has no equivalent override. Low value alone.
- #18492 Tiered recordings (per-tier retention: alerts vs detections vs motion drive separate cleanup windows). Nurby recording retention is flat. Reasonable future feature; not urgent.
- #18398 / #18540 Audio transcription (speech-to-text on audio events). Nurby audio is sound classification, not STT. Large separate feature.

Region remains ~90% N/A: forkserver/spawn arch (#18682, #18704), go2rtc restream (#18708), frame-cache debug (#18741/#18697), classification-model training+UI+metrics (#18595/#18583/#18571/#18475/#18474), TensorRT/Rockchip/Intel hwaccel (#18643/#18535/#18493), LPR OCR (#18505/#18390), birdseye/config-editor UI (#18628/#18383), docs and "Fixes" chores.

## Batch 26 (PRs 18380-18017)

Coverage-only batch. No issues filed, no fixes merged. Deep in Frigate's ML/hwaccel/multiprocess region, very high N/A density (many bare "Fixes"/"Translations" chores).

**HAVE (verified):**
- #18093 Refactor async ONVIF. Nurby's ONVIF/PTZ layer is already fully async: `services/discovery/onvif.py` uses `httpx.AsyncClient` (`_soap_request`), and `ptz_continuous_move/stop/get_presets/goto_preset` are all `async`; the only blocking work (device stream probes) is dispatched via `run_in_executor`. No blocking-in-event-loop problem to fix.
- #18353 Dynamic Config Updates / #18359 dynamic masks & zones. Same as batch-25 #18671 — Nurby zones/rules are DB-backed and flush perception caches via the rule-invalidation pubsub listener; no monolithic restart. N/A.

**N/A — feature/path absent in Nurby:**
- #18336 proxy-header separator (no `header_map`/`remote-role` proxy auth in Nurby).
- #18036 HF_ENDPOINT override (no hardcoded huggingface.co URLs in Nurby python; model download path differs).
- #18257 timezone handling (web/ display only; backend stores UTC).

**Backlog (gap-minor, no issue):**
- #18284 Min face configuration option — a minimum detected-face area threshold before running recognition, to skip tiny/low-quality faces. Nurby's face-embeddings pipeline has no equivalent min-face gate. Cheap future quality win.

Region outlook: PRs are now mostly ML classification config (#18380/#18362/#18475), hwaccel (ROCm/Jetson/Intel/Mesa/onnxruntime), i18n/docs, and unlabeled "Fixes" chores. Expect continued low hit-rate; watch for backend auth/API/security only.

## Batch 27 (PRs 18015-17831)

Two GAPs surfaced (1 new issue, 1 added to an existing issue). Rest is heavy i18n/docs/hwaccel/frontend N/A.

**GAP -> issue Eshpelin/nurby#69 (new, P3):** #17831 raised Frigate's RTSP read timeout 5s->10s to stop spurious disconnect/reconnect cycles on slow cameras. Nurby hardcodes `stimeout=5000000` (5s) at three ingest sites (`audio_worker.py:110`, `stream.py:394-395`, `audio/capture.py:98`). Filed as a tuning decision (not a blind bump) since the right value depends on Nurby's reconnect/backoff.

**GAP -> added to issue Eshpelin/nurby#65:** #17835 removed a hardcoded 30-day cap on Frigate's review-summary query that silently dropped older summaries. Nurby's `summaries.py:61-64` has the same class of defect as the recordings overlap bug #65 already tracks: `from`/`to` are filtered on `Summary.started_at` only, so a summary spanning the window boundary (started before `from`, ended inside) is dropped. Recommended fixing `recordings.py` and `summaries.py` together with interval-overlap predicates (`started_at <= to AND ended_at >= from`).

**N/A highlights:** PTZ autotrack motion estimation (#17955 — Frigate-specific), inter-process zmq/queue tuning (#17971/#17970/#17944 — Frigate multiprocess), RKNN/OpenVINO/Rockchip hwaccel, and a very large i18n/locale wave (#17979/17969/17953/17952/17942/17864/17861/17860/17858 etc.) plus docs/theme/UI. Frontend object-mask attributes (#18003) and face-library rename (#17879) are UI.

Region note: we have entered Frigate's big i18n/locale rollout and ML-classification era; backend signal is thinning. Keep scanning for auth/API/ingest correctness only.

## Batch 28 (PRs 17820-17640)

Coverage-only batch. No issues, no merges. Highest N/A density yet: this stretch is almost entirely hwaccel detector work (RKNN/hailo/MemryX/yolox/yolov9/onnx/tensorrt), the i18n/locale rollout (Polish/Russian/plurals/username keys), docs, UI, and LPR/face.

**Checked, N/A:** #17629 (search sort by score/speed) fixed a Frigate bug where in-Python sort used the wrong dict key (`x["score"]` vs `x["data"]["score"]`). Nurby does not have this bug class: search sorting is done in SQL via `order_by` (`services/search/query.py:172/208/249` cosine_distance + started_at), never an in-memory dict-key sort over a Frigate-style event blob. (#17629 is just below the cursor; will log in batch 29.)

**N/A:** #17712 async object detector and #17671 object tracking are Frigate's hardware inference loop / norfair tracker internals; Nurby uses a separate perception+VLM architecture. #17816 frame-time fix is `tracked_object.py` timing internals.

No backend auth/API/ingest signal in this batch. Region remains a hwaccel+i18n desert; keep scanning.

## Batch 29 (PRs 17639-17424)

Coverage-only batch. No issues, no merges. Dominated by LPR, Face Library UI, i18n/translations, and docs.

**HAVE (verified):** #17572 "Catch OpenAI compatible endpoint crash". Frigate's `genai/openai.py._send` only caught `TimeoutException` and dereferenced `result.choices` unguarded, so a connection error or malformed response crashed the call. Nurby is already defensive here: `services/agent/llm.py` delegates per-provider, and every call site wraps `llm_call`/VLM enrichment in a broad `except Exception` (`services/perception/vlm_enrichment_worker.py` lines 174/188/198/299/377/388/498/513, `services/agent/driver.py`, `services/recap.py`). An endpoint crash degrades to a logged failure, not a propagated exception.

**N/A worth noting (Frigate-internal, no Nurby analog):**
- #17629 search sort (confirmed batch-28: Nurby sorts in SQL `order_by`, not Frigate's in-memory dict-key sort).
- #17437 embedding eps (`metric.value =` shared-memory assignment), #17436 enrichments-eps graph — Frigate metrics internals.
- #17444 ceil-vs-round and #17438 frame-time-between-end-and-rounded-start — Frigate recording-segment timestamp edge cases tied to its segment cache; Nurby's snapshot/recording path differs.
- #17547 enabled-config cleanup — Frigate runtime config; Nurby DB-backed (see batch-25/26).

Rest: LPR (#17631/17592/17588/17549/17536/17453/17428), Face Library UI (#17630/17618/17530/17525/17521/17493/17472/17424), birdseye (#17502), i18n/docs. No backend auth/API/ingest signal.

## Batch 30 (PRs 17420-17305)

Coverage-only batch. No issues, no merges. Densest N/A region so far: face recognition / LPR / classification ML, hwaccel (tensorrt/nvidia/OpenVINO/RF-DETR/igpu), nginx/devcontainer infra, i18n, docs, and frontend UI.

**HAVE (verified):** #17339 "Ensure thumb camera directory exists before saving" added `os.makedirs(exist_ok=True)` before `cv2.imwrite` of an event thumbnail (Frigate previously wrote into a possibly-missing `THUMB_DIR/<camera>` dir, crashing on first event for a new camera). Nurby already does this at every image-write site: `services/perception/pipeline.py:_save_thumbnail` (makedirs THUMBNAIL_DIR), `services/perception/reid.py:_save_body_crop` (makedirs bodies dir), `services/perception/faces.py:218` (makedirs face_dir), and `services/agent/analyzer.py:990` (`root.mkdir(parents=True, exist_ok=True)` before imwrite at :996). Recording-segment writes also makedirs (`stream.py:268/301`). No missing-dir write crash exists in Nurby.

**N/A worth noting:**
- #17418 dynamic embeddings reindexing — Frigate re-embeds tracked objects when the user swaps the classification/embedding model from the UI. Nurby's embedding/reindex story is a known backlog item, not a defect; logged for the search initiative, no issue filed.
- #17307 onvif/norfair "bugfixes" — ONVIF/PTZ already verified fully async in batch-26; norfair tracker timing is Frigate-internal (Nurby uses separate perception+ReID).
- #17331/#17305/#17355 camera-enabled-state — all frontend (`CameraStreamingDialog.tsx`/`LiveCameraView.tsx`) gating of go2rtc metadata fetch; no backend analog.

Rest: face/LPR/classification ML (#17420/17412/17402/17401/17390/17387/17384/17373/17368/17337/17325/17308), hwaccel (#17411/17388/17321), nginx/devcontainer (#17419/17415/17400/17342/17341/17310), i18n/docs/UI. No backend auth/API/ingest correctness signal.

Region note: state.json had silently fallen 3 batches behind the ledger (cursor said 18017 while ledger/findings already covered batches 27-29 down to 17424, incl. issue #69). Reconciled this run. ledger/findings remain the source of truth; state cursor now corrected.

## Batch 31 (PRs 17298-17146)

Coverage-only batch. No issues, no merges. Same desert: face recognition / LPR / classification ML, Frigate+ settings UI, i18n/locale, hwaccel, docs.

**HAVE (verified):** #17187 "Fix Prometheus Metrics race condition". Frigate's `CustomCollector.collect()` reassigned and `del`-ed entries in shared `self.process_stats` while a concurrent scrape read it, causing intermittent KeyError and corrupt scrapes; fix works on a `.copy()`. Nurby's metrics module `services/perception/audio/metrics.py` is already race-safe: every read/write (`incr`/`gauge`/`observe_latency`/`snapshot`) is wrapped in a module-level `threading.Lock`, and `snapshot()` materializes brand-new lists/dicts inside the lock without mutating or deleting shared state. The admin endpoint (`services/api/routes/admin_stats.py`) just serves that snapshot. No shared-state mutation during read.

**N/A worth noting:**
- #17217 KeyError when `model.path` key missing — Frigate guards a config-file model.json lookup; Nurby config is DB-backed, no equivalent `config["model"]["path"]` file dereference.
- #17276 MQTT topic for camera review status — MQTT-specific integration; Nurby surfaces review/alert state via its own notify + pubsub, not MQTT.
- #17263/#17235/#17272 per-camera face/lpr config — Frigate pydantic config + LPR mixin gating; Nurby's perception/ReID pipeline is separate.
- #17273 disabled-cameras fix — Frigate ZMQ config-subscriber + frontend ws state.

Rest: face library UI/wizard (#17296/17245/17233/17213/17208/17203/17155/17152), face/LPR ML (#17290/17289/17244/17225/17202/17171/17146), hwaccel (#17298/17238), i18n/locale wave (#17258/17256/17239/17218/17198/17190/17184), nginx/ingress (#17248/17223), docs, frontend caching/filter (#17148/17147). No backend auth/API/ingest correctness signal.
