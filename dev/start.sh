#!/usr/bin/env bash
# Start the full Nurby dev stack locally.
#
# Starts Postgres, Redis, and MediaMTX via Docker Compose,
# runs the API + ingestion + perception services, and optionally
# starts a fake camera feed.
#
# Usage:
#   ./dev/start.sh              Start everything with synthetic testsrc camera
#   ./dev/start.sh --no-cam     Start without any fake camera
#   ./dev/start.sh --cctv       Loop the real CCTV sample clip via RTSP
#
# Logs land in dev/logs/{api,ingestion,perception,camera}.log

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/dev/logs"
mkdir -p "$LOG_DIR"

echo "==> Starting infrastructure (Postgres, Redis, MediaMTX)"
docker compose up -d postgres redis mediamtx

echo "==> Waiting for services to be healthy"
docker compose up --wait postgres redis 2>/dev/null

echo "==> Running database migrations"
python3 -m alembic upgrade head

echo "==> Starting API server (port 8000)"
python3 -m uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload \
  >"$LOG_DIR/api.log" 2>&1 &
API_PID=$!

echo "==> Starting ingestion service"
python3 -m services.ingestion.main \
  >"$LOG_DIR/ingestion.log" 2>&1 &
INGEST_PID=$!

echo "==> Starting perception service"
python3 -m services.perception.main \
  >"$LOG_DIR/perception.log" 2>&1 &
PERCEPT_PID=$!

CAM_PID=""
case "$1" in
  --no-cam)
    ;;
  --cctv)
    echo "==> Looping real CCTV sample clip to rtsp://localhost:8554/cam-cctv"
    bash dev/fake-cctv.sh rtsp://localhost:8554/cam-cctv \
      >"$LOG_DIR/camera.log" 2>&1 &
    CAM_PID=$!
    ;;
  *)
    echo "==> Starting synthetic RTSP camera (testsrc)"
    bash dev/fake-camera.sh rtsp://localhost:8554/cam-test \
      >"$LOG_DIR/camera.log" 2>&1 &
    CAM_PID=$!
    ;;
esac

echo ""
echo "Nurby dev stack running."
echo "  API         http://localhost:8000       (logs: $LOG_DIR/api.log)"
echo "  API docs    http://localhost:8000/docs"
echo "  WebRTC      http://localhost:8889"
echo "  Ingestion   (logs: $LOG_DIR/ingestion.log)"
echo "  Perception  (logs: $LOG_DIR/perception.log)"
if [[ -n "$CAM_PID" ]]; then
  echo "  Fake cam    (logs: $LOG_DIR/camera.log)"
fi
echo "  Frontend    cd frontend && npm run dev"
echo ""
echo "Tail all:  tail -F $LOG_DIR/*.log"
echo "Press Ctrl+C to stop all services."

cleanup() {
  echo ""
  echo "Shutting down."
  for pid in "$API_PID" "$INGEST_PID" "$PERCEPT_PID" "$CAM_PID"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "Done. Docker containers still running. Run 'docker compose down' to stop them."
}

trap cleanup INT TERM
wait
