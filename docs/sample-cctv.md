# Local sample CCTV fixtures

Nurby can process ordinary video files as camera inputs. This makes it
possible to exercise the camera, recording, perception, review, people, and
vehicle flows without a physical CCTV device or a remote video URL.

## Start the fixture stack

Place one or more `.mp4`, `.mov`, or `.mkv` files in `recordings/demo/`. The
repository includes `rec_mike_real.mp4` as a small local fixture. To create a
fresh, validated offline fixture, run:

```sh
scripts/build_sample_cctv_fixtures.sh
```

That creates a video-plus-tone clip for testing camera, recording, and audio
plumbing. The tone is deliberately not presented as speech and cannot prove
transcription. To test transcription, provide a real speech recording:

```sh
scripts/build_sample_cctv_fixtures.sh /path/to/speech.wav
```

The builder validates that both streams are present before returning. Then start
the stack with the read-only fixture overlay:

```sh
docker compose -f docker-compose.yml -f docker-compose.samples.yml up -d
```

The overlay mounts the host fixture directory as `/demo` inside ingestion and
perception. It does not change the normal deployment or expose host files to
the API container. It also enables the ingestion service's opt-in audio/STT
pipeline for this local QA profile; the default deployment remains audio-off
until an operator explicitly enables it.

## Register the files as cameras

Pass a JWT for an admin user. The script is idempotent by camera name, so it
can be rerun after adding or replacing fixtures:

```sh
scripts/seed_sample_cameras.sh http://localhost:4748 "$NURBY_TOKEN"
```

Each fixture becomes a `file` camera with recording mode `always`, object,
face, and plate detection enabled. When a file reaches EOF, the ingestion
worker reconnects and starts it again, which gives the rest of the system a
continuous CCTV-like source. Set the camera's recording mode to `off` from
the UI when you only want live perception without creating recordings.

The local fixture path is intentionally separate from the remote demo-camera
endpoint. That endpoint remains useful for onboarding, while this workflow is
deterministic and works offline.
