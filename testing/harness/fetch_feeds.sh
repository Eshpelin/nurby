#!/usr/bin/env bash
# One-time (idempotent) download of the UX-army camera-feed library into
# dev/feeds/. Each clip is normalized to 720p H.264 15fps silent video so
# start_stack.sh can publish them all with -c copy at near-zero CPU.
# Sources: intel-iot-devkit/sample-videos (Apache-2.0/CC0 detection
# clips) and Pexels free-license direct files. Best-effort: a failed
# download skips that feed with a warning, it does not abort the rest.
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p dev/feeds

SV="https://github.com/intel-iot-devkit/sample-videos/raw/master"

# name|url  (name becomes the RTSP path rtsp://localhost:8554/<name>)
FEEDS=(
  "front-door|$SV/one-by-one-person-detection.mp4"
  "street|$SV/person-bicycle-car-detection.mp4"
  "parking|$SV/car-detection.mp4"
  "shop-aisle|$SV/store-aisle-detection.mp4"
  "indoor-room|$SV/people-detection.mp4"
  "yard|$SV/worker-zone-detection.mp4"
  "lobby|$SV/classroom.mp4"
  "sidewalk|$SV/face-demographics-walking.mp4"
  # Pexels free-license direct files. IDs verified at fetch time; if the
  # CDN layout changes these just skip.
  "pets|https://videos.pexels.com/video-files/853770/853770-hd_1920_1080_25fps.mp4"
)

ok=0; failed=0
for entry in "${FEEDS[@]}"; do
  name="${entry%%|*}"; url="${entry#*|}"
  out="dev/feeds/$name.mp4"
  [ -s "$out" ] && { echo "have  $name"; ok=$((ok+1)); continue; }
  tmp="dev/feeds/.$name.raw"
  echo "fetch $name"
  if curl -fsSL --retry 2 -o "$tmp" "$url" && [ -s "$tmp" ]; then
    if ffmpeg -y -v error -i "$tmp" -an -vf "scale=1280:-2,fps=15" \
        -c:v libx264 -preset veryfast -crf 23 -g 30 -pix_fmt yuv420p \
        "$out" </dev/null; then
      ok=$((ok+1))
    else
      echo "WARN  $name: normalize failed, skipping" >&2
      rm -f "$out"; failed=$((failed+1))
    fi
  else
    echo "WARN  $name: download failed, skipping" >&2
    failed=$((failed+1))
  fi
  rm -f "$tmp"
done

echo "feeds ready: $ok, skipped: $failed"
ls -lh dev/feeds/*.mp4 2>/dev/null || true
