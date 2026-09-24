#!/usr/bin/env bash
# Register local video files as idempotent, recording-enabled sample cameras.
# Run the stack with docker-compose.samples.yml first so /demo is mounted in
# ingestion and perception containers.
#
# Usage:
#   scripts/seed_sample_cameras.sh API_BASE JWT_TOKEN [fixture-directory]
#
# The fixture directory defaults to recordings/demo. Every .mp4 file becomes
# one camera; re-running the script updates the matching camera instead of
# creating duplicates. The API accepts the container path, not the host path.
set -euo pipefail

API="${1:-http://localhost:4748}"
TOKEN="${2:-}"
FIXTURES="${3:-recordings/demo}"

if [[ -z "$TOKEN" ]]; then
  echo "usage: $0 API_BASE JWT_TOKEN [fixture-directory]" >&2
  exit 2
fi

if [[ ! -d "$FIXTURES" ]]; then
  echo "fixture directory does not exist: $FIXTURES" >&2
  exit 2
fi

FILES=()
while IFS= read -r file; do
  FILES+=("$file")
done < <(find "$FIXTURES" -maxdepth 1 -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' \) -print | sort)
if [[ "${#FILES[@]}" -eq 0 ]]; then
  echo "no sample video files found in $FIXTURES" >&2
  exit 2
fi

AUTH="Authorization: Bearer $TOKEN"
CAMERAS="$(curl -fsS -H "$AUTH" "$API/api/cameras")"

NURBY_SAMPLE_API="$API" NURBY_SAMPLE_TOKEN="$TOKEN" python3 - "$CAMERAS" "$FIXTURES" "${FILES[@]}" <<'PY'
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

cameras = json.loads(sys.argv[1])
fixture_dir = pathlib.Path(sys.argv[2]).resolve()
files = [pathlib.Path(p).resolve() for p in sys.argv[3:]]
api = os.environ.get("NURBY_SAMPLE_API", "http://localhost:4748")
token = os.environ["NURBY_SAMPLE_TOKEN"]

existing = {camera["name"]: camera for camera in cameras}

def request(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as response:
        return json.load(response)

for source in files:
    try:
        relative = source.relative_to(fixture_dir)
    except ValueError:
        raise SystemExit(f"fixture is outside fixture directory: {source}")

    stem = source.stem.replace("_", " ").replace("-", " ").strip().title()
    name = f"Sample CCTV - {stem}"
    payload = {
        "name": name,
        "stream_url": f"/demo/{relative.as_posix()}",
        "stream_type": "file",
        "location_label": "Sample CCTV",
        "recording_enabled": True,
        "recording_mode": "always",
        "detect_objects": True,
        "detect_faces": True,
        "detect_plates": True,
        "scene_mode": "indoor",
        "enabled": True,
    }
    camera = existing.get(name)
    if camera:
        result = request("PATCH", f"{api}/api/cameras/{camera['id']}", payload)
        action = "updated"
    else:
        result = request("POST", f"{api}/api/cameras", payload)
        action = "created"
    print(f"{action}: {result['name']} -> {result['stream_url']}")
PY
