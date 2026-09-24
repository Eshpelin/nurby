#!/usr/bin/env bash
# Build deterministic local CCTV fixtures for offline QA.
#
# By default this creates a valid video + tone-audio clip. Pass a real WAV or
# AIFF speech recording as the first argument to exercise transcription too:
#
#   scripts/build_sample_cctv_fixtures.sh /path/to/speech.wav
#
# Generated media belongs in recordings/demo/, which is intentionally ignored
# by git. The script validates the resulting container before returning.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${2:-${ROOT_DIR}/recordings/demo}"
SPEECH_SOURCE="${1:-}"
OUTPUT="${OUTPUT_DIR}/qa_pipeline.mp4"

command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 2; }
command -v ffprobe >/dev/null || { echo "ffprobe is required" >&2; exit 2; }
mkdir -p "$OUTPUT_DIR"

if [[ -n "$SPEECH_SOURCE" && ! -f "$SPEECH_SOURCE" ]]; then
  echo "speech source does not exist: $SPEECH_SOURCE" >&2
  exit 2
fi

if [[ -n "$SPEECH_SOURCE" ]]; then
  ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "testsrc=size=640x360:rate=15" \
    -i "$SPEECH_SOURCE" \
    -map 0:v:0 -map 1:a:0 -t 20 \
    -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 16000 -ac 1 -shortest \
    "$OUTPUT"
  AUDIO_KIND="speech source: $SPEECH_SOURCE"
else
  ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "testsrc=size=640x360:rate=15:duration=20" \
    -f lavfi -i "sine=frequency=440:sample_rate=16000:duration=20" \
    -map 0:v:0 -map 1:a:0 -t 20 \
    -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 16000 -ac 1 -shortest \
    "$OUTPUT"
  AUDIO_KIND="synthetic tone (audio plumbing only; not speech)"
fi

VIDEO_STREAMS="$(ffprobe -v error -select_streams v -show_entries stream=index -of csv=p=0 "$OUTPUT")"
AUDIO_STREAMS="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$OUTPUT")"
DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUTPUT")"

if [[ -z "$VIDEO_STREAMS" || -z "$AUDIO_STREAMS" ]]; then
  echo "fixture validation failed: expected both video and audio streams" >&2
  exit 1
fi

echo "created: $OUTPUT"
echo "duration: ${DURATION}s"
echo "audio: $AUDIO_KIND"
echo "validated: video and audio streams are present"
