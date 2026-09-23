# Choosing the media storage location

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
