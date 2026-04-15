#!/usr/bin/env bash
# Start the full Nurby dev stack locally.
#
# Starts Postgres, Redis, and MediaMTX via Docker Compose,
# runs the API server, and optionally starts a fake camera.
#
# Usage:
#   ./dev/start.sh           Start everything
#   ./dev/start.sh --no-cam  Start without fake camera

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Starting infrastructure (Postgres, Redis, MediaMTX)"
docker compose up -d postgres redis mediamtx

echo "==> Waiting for services to be healthy"
docker compose up --wait postgres redis 2>/dev/null

echo "==> Running database migrations"
python3 -m alembic upgrade head

echo "==> Starting API server (port 8000)"
python3 -m uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

if [[ "$1" != "--no-cam" ]]; then
  echo "==> Starting fake RTSP camera"
  bash dev/fake-camera.sh rtsp://localhost:8554/cam-test &
  CAM_PID=$!
fi

echo ""
echo "Nurby dev stack running."
echo "  API        http://localhost:8000"
echo "  API docs   http://localhost:8000/docs"
echo "  WebRTC     http://localhost:8889"
echo "  Frontend   cd frontend && npm run dev"
echo ""
echo "Press Ctrl+C to stop all services."

cleanup() {
  echo ""
  echo "Shutting down."
  kill $API_PID 2>/dev/null
  [[ -n "$CAM_PID" ]] && kill $CAM_PID 2>/dev/null
  wait 2>/dev/null
  echo "Done. Docker containers still running. Run 'docker compose down' to stop them."
}

trap cleanup INT TERM
wait
