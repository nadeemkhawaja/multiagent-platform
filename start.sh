#!/usr/bin/env bash
#
# start.sh — Launch the Multi-Agent Auto-Scheduling Platform (backend + frontend).
# Stops both cleanly on Ctrl+C.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 1. Check Ollama
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
curl -s --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1 || \
  echo "WARNING: Ollama not reachable at $OLLAMA_URL"

# 2. Python venv
if command -v python3.12 >/dev/null 2>&1; then PYTHON=python3.12; else PYTHON=python3; fi
if [ -d "venv" ] && ! venv/bin/python --version 2>/dev/null | grep -q "3.12"; then rm -rf venv; fi
if [ ! -d "venv" ]; then "$PYTHON" -m venv venv; fi
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 3. Frontend deps
if [ ! -d "frontend/node_modules" ]; then (cd frontend && npm install --silent); fi

# 4. Ensure logs directory exists
mkdir -p "$ROOT/logs"

# Write PIDs to file for stop.sh
PID_FILE="$ROOT/.platform.pids"

# 5. Start backend + frontend
(cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 5174 > ../logs/backend.log 2>&1) &
BACKEND_PID=$!
(cd frontend && npm run dev > ../logs/frontend.log 2>&1) &
FRONTEND_PID=$!

echo "$BACKEND_PID $FRONTEND_PID" > "$PID_FILE"

# 6. Open the dashboard in the default browser once the frontend is reachable
DASH_URL="http://localhost:5173"
open_browser() {
  if command -v open >/dev/null 2>&1; then open "$DASH_URL"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$DASH_URL" # Linux
  elif command -v start >/dev/null 2>&1; then start "$DASH_URL"       # Windows/Git Bash
  fi
}
(
  for _ in $(seq 1 30); do
    curl -s --max-time 1 "$DASH_URL" >/dev/null 2>&1 && break
    sleep 0.5
  done
  open_browser
) &

# Clean shutdown of both children on exit
cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
}
trap cleanup INT TERM EXIT

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "your-ip")
echo ""
echo "============================================================"
echo "  Dashboard (local):   http://localhost:5173"
echo "  Dashboard (network): http://$LOCAL_IP:5173"
echo "  API (local):         http://localhost:5174/docs"
echo "  API (network):       http://$LOCAL_IP:5174/docs"
echo "  Press Ctrl+C to stop, or run ./stop.sh from another terminal."
echo "============================================================"

wait
