#!/usr/bin/env bash
# Loop a real CCTV-style MP4 clip to MediaMTX as an RTSP stream.
# Use this to test the ingestion pipeline end-to-end with real motion,
# people, and vehicles instead of synthetic testsrc patterns.
#
# Usage:
#   ./dev/fake-cctv.sh                                 Default clip, default URL
#   ./dev/fake-cctv.sh rtsp://localhost:8554/cam-cctv  Custom RTSP URL
#   ./dev/fake-cctv.sh <rtsp-url> <file.mp4>           Custom file too

set -e

RTSP_URL="${1:-rtsp://localhost:8554/cam-cctv}"
CLIP="${2:-$(cd "$(dirname "$0")" && pwd)/sample-cctv.mp4}"

if [[ ! -f "$CLIP" ]]; then
  echo "Clip not found. $CLIP" >&2
  echo "Run the downloader or pass a path as second arg." >&2
  exit 1
fi

echo "Looping $CLIP to $RTSP_URL"
echo "Press Ctrl+C to stop."

# -stream_loop -1 loops forever. -re paces at real-time.
# Re-encode to H.264 yuv420p for broad decoder support.
ffmpeg -hide_banner -loglevel warning \
  -stream_loop -1 -re -i "$CLIP" \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 30 \
  -pix_fmt yuv420p -an \
  -f rtsp -rtsp_transport tcp \
  "$RTSP_URL"
