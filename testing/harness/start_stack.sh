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

if ! pgrep -f "sample-cctv.mp4" >/dev/null 2>&1; then
  nohup ffmpeg -re -stream_loop -1 -i dev/sample-cctv.mp4 -c copy \
    -f rtsp rtsp://localhost:8554/uxcam >testing/harness/ffmpeg.log 2>&1 &
  echo "rtsp loop publishing at rtsp://localhost:8554/uxcam"
fi

for _ in $(seq 1 30); do
  curl -sf "http://localhost:$API_PORT/api/health" >/dev/null 2>&1 && { echo "stack up"; exit 0; }
  sleep 1
done
echo "API did not become healthy; check testing/harness/api.log" >&2
exit 1
