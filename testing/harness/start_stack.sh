#!/usr/bin/env bash
# Boot the isolated UX-army stack: docker deps, nurby_uxtest DB, API on
# :8787, ingestion + perception on the host, looping CCTV RTSP feed
# published into mediamtx. Idempotent, so every scheduled run calls it
# and only missing pieces start.
#
#   testing/harness/start_stack.sh            # boot / repair
#   testing/harness/start_stack.sh --reset    # drop nurby_uxtest first
#   testing/harness/start_stack.sh --fresh    # net-new deploy: tear the
#       stack down, rebuild compose images, drop the DB, and restart the
#       host API/ingestion/perception on latest code. Every scheduled run
#       uses this so it deploys the current repo, not a stale process.
set -euo pipefail
cd "$(dirname "$0")/../.."

MODE="${1:-}"
BUILD_FLAG=""
if [ "$MODE" = "--fresh" ]; then
  echo "fresh deploy: tearing down uxtest compose stack"
  docker compose down --remove-orphans || true
  BUILD_FLAG="--build"
fi

UXDB_URL="postgresql+asyncpg://nurby:nurby_dev@localhost:5433/nurby_uxtest"
API_PORT=8787

# Own Redis DB index, NOT the default /0 the main dev stack uses. Motion
# keyframes travel over a Redis STREAM, which persists: sharing /0 meant
# uxtest perception woke up and replayed the dev stack's leftover
# keyframes, writing observations for `nurby` cameras that don't even
# exist in nurby_uxtest. Every uxtest process must agree on this index.
UXREDIS_URL="redis://localhost:6379/1"

# Ingestion and perception run on the HOST (like the API), not in
# compose. The compose services hardcode the `nurby` database and
# resolve peers by service name (postgres:5432, rtsp://mediamtx:8554),
# neither of which points at the uxtest stack. Running them on the host
# also means rtsp://localhost:8554/... - the URL a persona actually
# types into Add Camera - resolves to the same feed the harness
# publishes.
UXDATA="dev/uxtest-data"
mkdir -p "$UXDATA/recordings" "$UXDATA/thumbnails" "$UXDATA/audio"

# Keep the laptop awake until just past the next 3-hourly run.
pkill -f "caffeinate -dims -t 12600" 2>/dev/null || true
(caffeinate -dims -t 12600 >/dev/null 2>&1 &)

docker compose up -d $BUILD_FLAG postgres redis mediamtx

echo "waiting for postgres..."
for _ in $(seq 1 60); do
  docker compose exec -T postgres pg_isready -U nurby >/dev/null 2>&1 && break
  sleep 1
done

if [ "$MODE" = "--reset" ] || [ "$MODE" = "--fresh" ]; then
  docker compose exec -T postgres psql -U nurby -d postgres \
    -c "DROP DATABASE IF EXISTS nurby_uxtest;"
fi
docker compose exec -T postgres psql -U nurby -d postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname='nurby_uxtest'" | grep -q 1 || \
  docker compose exec -T postgres psql -U nurby -d postgres \
    -c "CREATE DATABASE nurby_uxtest OWNER nurby;"

PYTHONPATH=. DATABASE_URL="$UXDB_URL" .venv-test/bin/alembic upgrade head

# Env every uxtest process shares. Pointing at the uxtest DB, the uxtest
# Redis index, and scratch media paths outside the user's real data.
ux_env() {
  export PYTHONPATH=.
  export DATABASE_URL="$UXDB_URL"
  export REDIS_URL="$UXREDIS_URL"
  export MEDIAMTX_API_URL="http://localhost:9997"
  export MEDIAMTX_RTSP_URL="rtsp://localhost:8554"
  export RECORDINGS_PATH="$UXDATA/recordings"
  export THUMBNAILS_PATH="$UXDATA/thumbnails"
  export AUDIO_STORAGE_PATH="$UXDATA/audio"
  export NURBY_MODELS_DIR="services/perception/models"
  # USB/webcam bridging can't work headless here, and a persona's
  # cameras are all RTSP anyway.
  export DISABLE_WEBCAM_BRIDGE=1
}

# A fresh deploy must run the current repo, so kill the long-lived host
# processes first; the idempotent guards below then restart them on the
# latest code instead of leaving a stale API/worker up.
if [ "$MODE" = "--fresh" ]; then
  pkill -f "uvicorn services.api.main:app" 2>/dev/null || true
  pkill -f "services.ingestion.main" 2>/dev/null || true
  pkill -f "services.perception.main" 2>/dev/null || true
  sleep 1
fi

if ! lsof -iTCP:$API_PORT -sTCP:LISTEN >/dev/null 2>&1; then
  (ux_env; nohup .venv-test/bin/uvicorn services.api.main:app \
    --port $API_PORT >testing/harness/api.log 2>&1 &)
  echo "api starting on :$API_PORT"
fi

# Without these two, cameras never leave "offline" and no detection ever
# lands: the dashboard just says "Nothing happened yet" forever, which
# silently makes every persona's core goal (did anyone come to the door?)
# untestable. pgrep guards keep this idempotent across runs.
start_worker() { # $1 = module, $2 = log name
  if pgrep -f "$1" >/dev/null 2>&1; then
    echo "$2 already running"
    return 0
  fi
  (ux_env; nohup .venv-test/bin/python -m "$1" \
    >"testing/harness/$2.log" 2>&1 &)
  echo "$2 starting"
}
start_worker services.ingestion.main ingestion
start_worker services.perception.main perception

# Feed library: each scene pool dev/feeds/<scene>/ publishes ONE
# looping variant at rtsp://localhost:8554/<scene>, and the variant
# rotates with runs_completed so the same camera sees different footage
# on different runs. Scene map in testing/harness/feeds.json;
# fetch_feeds.sh (re)downloads and content-gates the library.
[ -d dev/feeds/street ] || testing/harness/fetch_feeds.sh

RUN_IDX=$(python3 -c "import json;print(json.load(open('testing/state.json'))['runs_completed'])" 2>/dev/null || echo 0)

publish_loop() { # $1 = file, $2 = rtsp path name
  if pgrep -f "rtsp://localhost:8554/$2\$" >/dev/null 2>&1; then
    # right variant already up -> leave it; wrong one -> replace
    pgrep -f "[-]i $1 .*rtsp://localhost:8554/$2\$" \
      >/dev/null 2>&1 && return 0
    pkill -f "rtsp://localhost:8554/$2\$" 2>/dev/null || true
    sleep 1
  fi
  nohup ffmpeg -re -stream_loop -1 -i "$1" -c copy \
    -rtsp_transport tcp -f rtsp "rtsp://localhost:8554/$2" \
    >>testing/harness/ffmpeg.log 2>&1 &
  echo "rtsp loop: $2 <- $(basename "$1")"
}

publish_loop dev/sample-cctv.mp4 uxcam
for d in dev/feeds/*/; do
  scene="$(basename "$d")"
  [ "$scene" = ".rejected" ] && continue
  variants=("$d"*.mp4)
  [ -e "${variants[0]}" ] || continue
  publish_loop "${variants[$((RUN_IDX % ${#variants[@]}))]}" "$scene"
done

for _ in $(seq 1 30); do
  curl -sf "http://localhost:$API_PORT/api/health" >/dev/null 2>&1 && { echo "stack up"; exit 0; }
  sleep 1
done
echo "API did not become healthy; check testing/harness/api.log" >&2
exit 1
