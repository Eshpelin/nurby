# Storage architecture: where recordings live

Two decisions decide where a recording lands, in priority order:

1. **Per camera** — `cameras.storage_profile_id`. A camera with a profile
   records under that profile's root. Set per camera in the camera's
   settings ("Storage Location"); this is the "this camera goes to my
   second drive" control (issue #251).
2. **Global fallback** — the `storage_recordings_dir` app setting (setup
   wizard / Settings → Storage location), falling back to the
   env-provided default (`RECORDINGS_PATH`, i.e. the compose volume).

`shared/storage_paths.recordings_root_for(camera_id)` is the single
resolution point; the ingestion worker resolves it when the worker
starts, and every serve/containment path resolves it per recording, so a
recording is always read back from the root it was written to.

## Layout on disk

Each camera keeps its own subtree under whatever root it records into:

```
<root>/<camera_id>/<YYYY-MM-DD>/<camera_id>_<HHMMSS>.mp4
<root>/<camera_id>/.preroll/…          (pre-roll staging, never in the DB)
<root>/clips/<camera_id>/<conv_id>.mp4 (conversation clips)
<root>/annotated, <root>/guardian_blurred  (derived caches)
```

Moving a camera between roots affects **new** segments only; files
already written stay where they are, and old recordings stop resolving
until the files are moved or the setting reverted. The UI says this
wherever the choice is offered.

## Storage profiles and remote backends

A `storage_profiles` row is `{name, kind, root, enabled}`. Cameras point
at a profile; deleting a profile drops those cameras back to the global
root (FK is `ON DELETE SET NULL`).

**kind="local" (implemented)** — `root` is an absolute directory on a
filesystem the backend process can see. This covers a second internal
drive, a USB disk, and — crucially — **mounts of remotes**:

| Remote you have | How to expose it as a local root |
|---|---|
| FTP / SFTP | `rclone mount remote: /mnt/ftp-recordings` (or sshfs) |
| SMB / Windows share | mount.cifs / Docker volume of the host mount |
| WebDAV | `rclone mount` with a `--vfs-cache` for writes (S3 is native now) |
| Another Nurby/file server | NFS export, or WebDAV via davfs2/rclone |

Mounts are the honest v1 answer to "my own FTP": the app keeps treating
storage as a POSIX path, playback (HTTP range requests) and retention
keep working unchanged, and the remote's flakiness stays an ops concern
rather than an app code path.

**kind="ftp" (implemented, native)** — a real FTP/FTPS writer, built as
**buffer-then-upload** so recording never depends on the network:

1. Segments are written locally first (the camera keeps buffering to the
   global root — an FTP profile never changes the local write path).
2. At finalize time the recording is marked `pending` with a snapshot of
   which profile owns it (`remote_profile_id`).
3. The ingestion **upload worker** (30 s cadence, oldest first) transfers
   segments with size verification, then deletes the local copy
   (`delete_after_upload`, default on). Failures retry up to 20 attempts;
   the terminal `failed` state keeps the local copy and surfaces in the
   storage overview warnings.
4. **Playback** falls back to FTP: the first request for an
   uploaded-and-removed recording downloads it into
   `<recordings root>/.remote_cache` (LRU-capped at ~20 GB) and serves
   from there, so HTTP range requests and seeking work unchanged.
5. **Retention** deletes the remote object using the profile snapshot.

Credentials are Fernet-sealed on the profile (`config_enc`) and never
echoed by the API (responses carry a masked config plus `has_password`).

Known v1 limitations: agent/VLM clip analysis reads the local buffer, so
segments already uploaded and removed are analyzed best-effort only (the
upload cadence leaves near-time analysis working); changing a camera's
profile or deleting one can orphan already-uploaded remote files (the
per-recording snapshot covers retention, not reassignments).

**kind="s3" (implemented, native, #270)** — AWS S3, Cloudflare R2,
Backblaze B2, Wasabi and MinIO through one boto3 client (`endpoint_url`
selects the non-AWS ones). Same buffer-then-upload pipeline and worker as
FTP. `root` is the key prefix. Config: bucket, region, endpoint, access
key, secret (sealed), storage class. The connection test writes and
deletes a tiny `STANDARD` marker object, so it proves write access without
archive-class minimum charges. Playback downloads into the same
`.remote_cache`. For `GLACIER` / `DEEP_ARCHIVE` objects (set directly, or
moved there by a bucket lifecycle rule) the first playback requests a
7-day restore and answers 409 with an ETA; `GLACIER_IR` plays instantly.

**kind="webdav" (designed, not built)** — the create API rejects
unimplemented kinds.

## Archive tier: keep recent footage local, move old footage out (#270)

Settings → Storage → **Archive older recordings** picks a remote profile
(S3 or FTP) as the archive (`archive_profile_id` app setting) and how long
the archive keeps footage (`archive_retention_days`, 0 = forever).

With an archive set, a camera's retention means *how long footage stays on
this machine*:

- **By age**: a recording older than `retention_days` is queued for the
  archive (`remote_state=pending`, `remote_profile_id=<archive>`) instead of
  deleted. The upload worker moves it and always removes the local copy
  once the upload is verified.
- **By size**: the budget counts local bytes only; the oldest local
  recordings are queued for the archive until the camera is under it.
- **Keep forever**: nothing is archived. The Archive card lists these
  cameras.
- A recording the archive owns (uploaded, pending, or failed) is never
  deleted by local retention. A failed archive upload keeps its local file
  (the only copy) and shows as a storage warning.
- The archive is pruned hourly by `archive_retention_days`. A row is
  dropped only after its remote object is deleted, so a failed delete
  retries instead of leaving a billed orphan.
- The archive destination cannot be deleted while it is selected, and a
  destination that goes missing or disabled raises a storage warning
  (recordings are then deleted as if archiving were off).

No migration: the archive reuses `recordings.remote_*` and two app
settings.

Code: `shared/archive.py`, `services/ingestion/retention.py`
(`mark_for_archive`, `_enforce_archive_retention`),
`services/api/routes/storage_profiles.py` (`/api/storage/archive`),
`frontend/src/components/settings/ArchiveCard.tsx`.

## Where resolution happens (code map)

- Worker start: `StreamWorker.run` → `recordings_root_for(camera_id)` →
  `self._recordings_root` (segments + pre-roll).
- Serving/containment: recordings routes (`_contained_recording_path`),
  retention (`_resolve_camera_path`), agent clip analysis,
  VLM enrichment frames, conversation clips, guardian clip streaming.
- Cache: per-process, ~30 s throttle in `shared/storage_paths`;
  profile CRUD and camera storage changes invalidate (camera PATCH also
  emits the stream-restart signal so the worker re-resolves).
