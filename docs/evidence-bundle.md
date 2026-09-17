# Evidence bundle export (#225)

An evidence bundle packages the recordings that match an export selection into a
single downloadable zip, together with a machine-readable `manifest.json` at the
archive root. The manifest binds the media to its provenance so the bundle is
credible when handed to police, an insurer, or the other side of a Guardian
custody handover, instead of being an unexplained pile of MP4s.

## Endpoint

`GET /recordings/evidence-bundle`

Takes the same filters as the plain bundle download (`camera_id`, `from`, `to`,
`object`, `person_id`, `vehicle_id`) plus a `?token=`. It returns a
`nurby-evidence-bundle.zip` containing:

- Each matching recording's original media file.
- `manifest.json` at the archive root.

The bundle is capped by file count and total size like the plain download; an
over-broad range returns 413 asking to narrow the window.

## What the manifest contains

Top level: a schema `manifest_version`, `generated_at_utc`, `generated_by` (the
exporting user), `nurby_version` + `build_sha`, the caller's `camera_scope` at
export time, the `hash_algorithm` (`sha256`), a `file_count`, and a `disclaimer`.

Per file, under `files[]`:

- `file` — its name inside the archive.
- `sha256` — the hash of the **bytes actually shipped in this bundle**, so a
  recipient verifies exactly what they hold by recomputing it.
- `size_bytes`.
- `camera_id`, `camera_name` — the source camera.
- `recording_id` — the source row id.
- `captured_start_utc`, `captured_end_utc`, `captured_start_local` — capture
  timestamps in UTC and the stored local wall-clock.
- `processing` — `{"kind": "original"}` for pristine source footage, or a
  derived label (e.g. `{"kind": "annotated"}`, `{"kind": "blurred"}`) for a
  re-render, with `derived: true` and, when the original is retained,
  `source_sha256` referencing it.

## Camera scope

The export is scoped to the caller's allowed cameras via
`shared/camera_access.py` (issues #40 / #201). No camera the caller cannot see
can appear in the bundle or its manifest, and `camera_scope` records the ACL
that was in force.

## What the manifest does and does not attest

The manifest **does** attest that:

- Nurby recorded each listed file from the named camera at the listed times.
- The `sha256` matches the exact bytes shipped, so tampering after export is
  detectable by recomputing the hash.
- Derived media (annotated / blurred re-renders) is labeled as processed, not
  passed off as untouched source.

The manifest **does not** attest to:

- A legal chain of custody. It records what Nurby exported, not who handled the
  bundle afterward or how it was stored.
- Anything outside Nurby's recording (the wider scene, intent, or events off
  camera).

This caveat also ships inside the manifest (`disclaimer`) so it travels with the
bundle rather than living only in these docs.

## Verifying a bundle

For each entry in `files[]`, recompute the SHA-256 of the named file inside the
zip and compare it to the entry's `sha256`. Any mismatch, or any file present in
the zip but absent from the manifest, means the bundle was altered after export.
