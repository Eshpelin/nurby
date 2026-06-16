# Findings

Curated, human-readable view of mapped Frigate PRs. Newest first. Raw rows: `ledger.jsonl`.
Status legend: HAVE · PARTIAL · MISSING · N/A. Priority: P0–P3. Effort: S/M/L/XL.

---

## P0 — Security

### [#23478] ffmpeg export args: blocklist → allowlist · `record` · PARTIAL
**Frigate:** Their blocklist guarding non-admin custom export ffmpeg args was bypassable many
ways (stream-specifier filters, scheme-less protocols, `tee`/preset/`-/option` file access,
bare extra-output tokens), allowing arbitrary file read/write and SSRF. They swapped it for an
**allowlist** of encoder flags plus a safe-filter list.
**Nurby:** `shared/netpolicy.py` handles webhook SSRF, but the **ffmpeg argument surface is
unaudited**. SSRF was a *deliberate skip* (overnight-review memory). Any place we pass
user-influenced values into ffmpeg (clip export, `stream_url`, MediaMTX mux config) is a
candidate for the same class of bypass.
**Action:** Audit every user-influenced ffmpeg invocation and stream URL. Replace any
blocklist/sanitize approach with a structural allowlist. Constrain protocols + file paths.
**Priority:** P0 · **Effort:** M

---

## P2 — Feature parity

### [#23387] Hide cameras from the review feed · `review` · PARTIAL
**Frigate:** Added a *second* visibility flag — hide a camera from the review/alerts feed,
independent of hiding it from the live dashboard. Recording continues.
**Nurby:** Camera-wall customization (commit `b870614`) hides tiles from the dashboard. No
separate "exclude from timeline/alerts feed" control found.
**Action:** Add a per-camera `exclude_from_review` flag distinct from dashboard hide. Camera
still records; it drops out of the timeline/alerts feed and their filters.
**Priority:** P2 · **Effort:** S

---

## P3 — Already covered (recorded for coverage)

### [#23326] Restore runtime state on startup · `comms` · HAVE
**Frigate:** Persists runtime toggles (camera on/off, detect, recordings, snapshots, audio)
across restarts via `.runtime_state.json` overlaid on the YAML provisioning source, cleared on
explicit config save / profile switch.
**Nurby:** Config is DB-driven (cameras + `app_settings` in Postgres), so runtime toggles
already survive restarts by architecture. Frigate needed this only because YAML is its
provisioning source. Nothing to do — note the provisioning-vs-runtime precedence nuance if we
ever add config "profiles."
**Priority:** P3 · **Effort:** —
