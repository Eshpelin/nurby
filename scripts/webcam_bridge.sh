#!/usr/bin/env bash
#
# Start the host-side webcam bridge daemon.
#
# Run this on the machine that owns the camera (your Mac or the self-hosted
# host). It reads cameras from the database and supervises ffmpeg processes
# that publish each local capture device to MediaMTX over RTSP.
#
# Requires ffmpeg on PATH. Uses the repo's Python env.
#
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found on PATH. Install with: brew install ffmpeg" >&2
  exit 1
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://nurby:nurby_dev@localhost:5433/nurby}"
export MEDIAMTX_RTSP_URL="${MEDIAMTX_RTSP_URL:-rtsp://localhost:8554}"

echo "nurby webcam bridge"
echo "  db:       $DATABASE_URL"
echo "  mediamtx: $MEDIAMTX_RTSP_URL"

exec python -m services.ingestion.host_bridge_main
