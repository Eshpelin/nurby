#!/usr/bin/env bash
# Idempotent download of the UX-army camera-feed library into scene
# pools: dev/feeds/<scene>/<slug>.mp4. start_stack.sh publishes one
# variant per scene and rotates variants across runs.
#
# Every clip is normalized (H.264, 15fps, <=1280w, silent, <=240s) so
# publishing is -c copy at near-zero CPU, then content-gated with YOLO
# (testing/harness/gate_clip.py): a clip only joins a pool if it really
# contains what the scene promises. Rejects land in dev/feeds/.rejected/.
#
# Sources, all direct-download and license-clean, no API keys:
#   intel-iot-devkit/sample-videos (Apache-2.0/CC0 detection clips)
#   CAVIAR (EC-funded fixed-camera lobby dataset, public download)
#   UR Fall Detection (falls + daily activities, public download)
#   Pexels free-license direct files
# Best-effort: a failed download or gate skips that clip, never aborts.
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p dev/feeds/.rejected

SV="https://github.com/intel-iot-devkit/sample-videos/raw/master"
CV="https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1"
UF="https://fenix.ur.edu.pl/~mkepski/ds/data"

# scene|slug|url
FEEDS=(
  "front-door|intel-one-by-one|$SV/one-by-one-person-detection.mp4"
  "street|intel-person-bicycle-car|$SV/person-bicycle-car-detection.mp4"
  "parking|intel-car|$SV/car-detection.mp4"
  "shop-aisle|intel-store-aisle|$SV/store-aisle-detection.mp4"
  "shop-aisle|intel-fruit-veg|$SV/fruit-and-vegetable-detection.mp4"
  "indoor-room|intel-people|$SV/people-detection.mp4"
  "indoor-room|intel-head-pose-female|$SV/head-pose-face-detection-female.mp4"
  "indoor-room|intel-head-pose-male|$SV/head-pose-face-detection-male.mp4"
  "indoor-room|intel-head-pose-both|$SV/head-pose-face-detection-female-and-male.mp4"
  "yard|intel-worker-zone|$SV/worker-zone-detection.mp4"
  "lobby|intel-classroom|$SV/classroom.mp4"
  "sidewalk|intel-face-demographics|$SV/face-demographics-walking.mp4"
  "sidewalk|intel-face-demographics-pause|$SV/face-demographics-walking-and-pause.mp4"
  "pets|pexels-dog|https://videos.pexels.com/video-files/853770/853770-hd_1920_1080_25fps.mp4"
)

# CAVIAR: INRIA entrance-hall fixed camera. Walking/browsing/meeting
# clips feed the lobby pool; bag-drop and fight clips are deliberate
# incident material for review/alert flows; Rest_* (slump/fall on
# floor) go to guardian-room.
CAVIAR_LOBBY=(Walk1 Walk2 Walk3 Browse1 Browse2 Browse3 Browse4
  Browse_WhileWaiting1 Browse_WhileWaiting2 Meet_Crowd Meet_Split_3rdGuy
  Meet_WalkSplit Meet_WalkTogether1 Meet_WalkTogether2 LeftBag
  LeftBag_AtChair LeftBag_BehindChair LeftBag_PickedUp LeftBox
  Fight_Chase Fight_OneManDown Fight_RunAway1 Fight_RunAway2)
CAVIAR_GUARDIAN=(Rest_InChair Rest_SlumpOnFloor Rest_WiggleOnFloor Rest_FallOnFloor)
for c in "${CAVIAR_LOBBY[@]}"; do
  FEEDS+=("lobby|caviar-$(echo "$c" | tr 'A-Z_' 'a-z-')|$CV/$c/$c.mpg")
done
for c in "${CAVIAR_GUARDIAN[@]}"; do
  FEEDS+=("guardian-room|caviar-$(echo "$c" | tr 'A-Z_' 'a-z-')|$CV/$c/$c.mpg")
done

# UR Fall Detection: fall-* clips end with a person on the floor,
# adl-* are normal daily activities (the negative case).
for i in $(seq -w 1 15); do
  FEEDS+=("guardian-room|urfall-fall-$i|$UF/fall-$i-cam0.mp4")
done
for i in $(seq -w 1 10); do
  FEEDS+=("guardian-room|urfall-adl-$i|$UF/adl-$i-cam0.mp4")
done

gate_classes() {
  case "$1" in
    parking) echo "car,truck,bus" ;;
    pets) echo "dog,cat" ;;
    *) echo "person" ;;
  esac
}

ok=0; failed=0; rejected=0
for entry in "${FEEDS[@]}"; do
  scene="${entry%%|*}"; rest="${entry#*|}"
  slug="${rest%%|*}"; url="${rest#*|}"
  out="dev/feeds/$scene/$slug.mp4"
  [ -s "$out" ] && { ok=$((ok+1)); continue; }
  [ -s "dev/feeds/.rejected/$scene-$slug.mp4" ] && { rejected=$((rejected+1)); continue; }
  mkdir -p "dev/feeds/$scene"
  tmp="dev/feeds/.$slug.raw"
  echo "fetch $scene/$slug"
  if curl -fsSL --retry 2 -o "$tmp" "$url" && [ -s "$tmp" ]; then
    if ffmpeg -y -v error -i "$tmp" -an -t 240 \
        -vf "scale='min(1280,iw)':-2,fps=15" \
        -c:v libx264 -preset veryfast -crf 23 -g 30 -pix_fmt yuv420p \
        "$out" </dev/null; then
      if .venv-test/bin/python testing/harness/gate_clip.py "$out" "$(gate_classes "$scene")"; then
        ok=$((ok+1))
      else
        echo "GATE  $scene/$slug rejected (content check failed)" >&2
        mv "$out" "dev/feeds/.rejected/$scene-$slug.mp4"
        rejected=$((rejected+1))
      fi
    else
      echo "WARN  $scene/$slug: normalize failed, skipping" >&2
      rm -f "$out"; failed=$((failed+1))
    fi
  else
    echo "WARN  $scene/$slug: download failed, skipping" >&2
    failed=$((failed+1))
  fi
  rm -f "$tmp"
done

echo "pool clips: $ok, download/normalize failures: $failed, gate-rejected: $rejected"
for d in dev/feeds/*/; do
  [ -d "$d" ] || continue
  echo "  $(basename "$d"): $(ls "$d"*.mp4 2>/dev/null | wc -l | tr -d ' ') variants"
done
