# Choosing the media storage location

Where Nurby keeps recordings is decided at one of two layers, depending
on how you run it. Both exist because "where is the video going to live?"
is the first question a new install has to answer (issue #251).

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
