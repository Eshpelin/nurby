#!/usr/bin/env bash
# Boot the isolated UX-army stack: docker deps, nurby_uxtest DB, API on
# :8787, looping CCTV RTSP feed published into mediamtx. Idempotent, so
# every scheduled run calls it and only missing pieces start.
#
#   testing/harness/start_stack.sh            # boot / repair
#   testing/harness/start_stack.sh --reset    # drop nurby_uxtest first
set -euo pipefail
cd "$(dirname "$0")/../.."

UXDB_URL="postgresql+asyncpg://nurby:nurby_dev@localhost:5433/nurby_uxtest"
API_PORT=8787

# Keep the laptop awake until just past the next 3-hourly run.
pkill -f "caffeinate -dims -t 12600" 2>/dev/null || true
(caffeinate -dims -t 12600 >/dev/null 2>&1 &)

docker compose up -d postgres redis mediamtx

echo "waiting for postgres..."
for _ in $(seq 1 60); do
  docker compose exec -T postgres pg_isready -U nurby >/dev/null 2>&1 && break
  sleep 1
done

if [ "${1:-}" = "--reset" ]; then
  docker compose exec -T postgres psql -U nurby -d postgres \
    -c "DROP DATABASE IF EXISTS nurby_uxtest;"
fi
docker compose exec -T postgres psql -U nurby -d postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname='nurby_uxtest'" | grep -q 1 || \
  docker compose exec -T postgres psql -U nurby -d postgres \
    -c "CREATE DATABASE nurby_uxtest OWNER nurby;"

PYTHONPATH=. DATABASE_URL="$UXDB_URL" .venv-test/bin/alembic upgrade head

if ! lsof -iTCP:$API_PORT -sTCP:LISTEN >/dev/null 2>&1; then
  PYTHONPATH=. DATABASE_URL="$UXDB_URL" nohup .venv-test/bin/uvicorn services.api.main:app \
    --port $API_PORT >testing/harness/api.log 2>&1 &
  echo "api starting on :$API_PORT"
fi

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
