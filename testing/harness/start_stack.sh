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

# Feed library: every clip in dev/feeds/ becomes its own looping RTSP
# path (scene map in testing/harness/feeds.json). fetch_feeds.sh
# downloads the library; the legacy uxcam path stays for old cameras.
[ -s dev/feeds/street.mp4 ] || testing/harness/fetch_feeds.sh
publish_loop() { # $1 = file, $2 = rtsp path name
  pgrep -f "rtsp://localhost:8554/$2" >/dev/null 2>&1 && return 0
  nohup ffmpeg -re -stream_loop -1 -i "$1" -c copy \
    -rtsp_transport tcp -f rtsp "rtsp://localhost:8554/$2" \
    >>testing/harness/ffmpeg.log 2>&1 &
  echo "rtsp loop: rtsp://localhost:8554/$2"
}
publish_loop dev/sample-cctv.mp4 uxcam
for f in dev/feeds/*.mp4; do
  [ -e "$f" ] || continue
  publish_loop "$f" "$(basename "$f" .mp4)"
done

for _ in $(seq 1 30); do
  curl -sf "http://localhost:$API_PORT/api/health" >/dev/null 2>&1 && { echo "stack up"; exit 0; }
  sleep 1
done
echo "API did not become healthy; check testing/harness/api.log" >&2
exit 1
