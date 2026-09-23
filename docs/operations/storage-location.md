# Choosing the media storage location

Where Nurby keeps recordings is decided at one of two layers, depending
on how you run it. Both exist because "where is the video going to live?"
is the first question a new install has to answer (issue #251).

Per-camera overrides (a second drive, or a mount of your FTP/SMB/S3
remote) sit on top of both and are described in
[storage architecture](../storage-architecture.md).

The operator-facing surface is **Settings → Storage**: one card showing
each media root (recordings / thumbnails / audio) with its effective
path, writable status, and free space; the recordings location control;
per-camera usage and retention; and low-space warnings (issue #266). It
is also the first step of the onboarding wizard.

## In the app: the storage location setting

The first-run wizard opens with **"Where should recordings be stored?"**;
the same control lives in **Settings → Storage location**. Enter an
absolute path (Windows drives like `D:\Nurby\recordings` work on native
installs), hit **Check** — Nurby creates the folder, verifies it is
writable, and reports free space — then **Use this location**.

- Under the hood this is the `storage_recordings_dir` app setting
  (`GET/POST /api/system/storage*`, `PATCH /api/system/settings`),
  applied process-wide by `shared/storage_paths` without a restart.
- **New recordings only.** Files already written stay in the previous
  location, and the app serves paths against the current root — move old
  footage manually (or revert the setting) if you need it back. This is
  why the wizard asks before your first camera exists.
- Recordings-derived caches (annotated clips, guardian blur cache) follow
  the same root. Thumbnails and audio stay on their configured paths.
- In Docker, pick a path mounted into the container. Windows drive paths
  are rejected with guidance pointing at the compose knob below, because
  a `D:\...` path inside a Linux container would silently lose footage.

## In Docker Compose: the volume source

Docker Compose keeps recordings, thumbnails, and audio in named volumes by
default. To place them on another drive, copy `.env.example` to `.env` and set
the volume sources before starting the stack:

```dotenv
NURBY_RECORDINGS_VOLUME=D:/Nurby/recordings
NURBY_THUMBNAILS_VOLUME=D:/Nurby/thumbnails
NURBY_AUDIO_VOLUME=D:/Nurby/audio
```

On Linux or macOS, use absolute paths such as
`/srv/nurby/recordings`. Docker Desktop must be allowed to access the selected
drive. The directories must be writable by the containers. Existing named
volumes are not copied automatically; migrate them before switching sources if
they contain recordings you need to keep.

Which layer wins: the compose volume decides what the container can see
at `/data/recordings` (the `RECORDINGS_PATH` the services get); the app
setting then chooses a directory under — or instead of — that root. For
"put it on my D: drive", set the volume in `.env`; the in-app picker is
the right tool on native installs and for pointing recordings at any
already-mounted directory.

## API surface

- `GET /api/system/storage` — storage overview (issue #266): every media
  root with effective path, writable status, capacity, low-space
  warnings, and a Docker flag. Admin-only.
- `POST /api/system/storage/validate` — probe a candidate directory
  (absolute-path check, creation, write test, capacity). Admin-only.
- `PATCH /api/system/settings` with `storage_recordings_dir` — save the
  location. Admin-only, takes effect immediately for new writes.
- `GET/POST/PATCH/DELETE /api/storage-profiles` — per-camera locations.
- `GET /api/storage` — usage and retention metrics per camera (DB
  numbers, independent of which root the files live under).

## Migration statement

Changing a location never moves, copies, or deletes existing media.
New writes land in the new location; existing files stay where they are
and stop resolving until moved manually or the setting is reverted.
Database rows store root-relative paths, so moving files back under the
previous root (or copying them to the new one) restores playback with no
DB changes. Docker volume renames likewise never migrate contents.

## Before / after verification procedure

When changing a location, verify in this order:

1. **Before:** Settings → Storage shows the current effective paths and
   a green (writable) dot per root. `GET /api/system/storage` returns
   `writable: true` for recordings.
2. **Change:** Check → save the new location (or set the env volume and
   restart the stack). The settings response reflects the new root
   without a restart.
3. **After:** add a camera or trigger a recording; within seconds a new
   segment appears under the new root, and Settings → Storage shows the
   green writable dot with updated free space on that volume. Play the
   newest recording end-to-end (timeline → clip) to confirm serving.
4. **Rollback:** revert the setting (or env) — the old paths resolve
   again, and no media was touched in the meantime.
