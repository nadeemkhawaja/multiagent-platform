#!/usr/bin/env bash
# =============================================================================
# start.sh — Launch the Multi-Agent Platform (backend + frontend)
#
# Usage:  ./start.sh              Opens two Terminal tabs (macOS default)
#         ./start.sh --no-tabs    Runs both in background, logs to ./logs/
# =============================================================================

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

NO_TABS=false
[[ "${1:-}" == "--no-tabs" ]] && NO_TABS=true

# ── 1. Ollama check ───────────────────────────────────────────────────────────
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
if ! curl -s --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "⚠  WARNING: Ollama not reachable at $OLLAMA_URL"
  echo "   Start it with:  ollama serve"
  echo ""
fi

# ── 2. Python venv ────────────────────────────────────────────────────────────
if command -v python3.12 >/dev/null 2>&1; then PYTHON=python3.12; else PYTHON=python3; fi
if [ ! -d "venv" ]; then
  echo "→ Creating Python venv..."
  "$PYTHON" -m venv venv
fi
source venv/bin/activate
echo "→ Installing Python deps (quick check)..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── 3. Frontend deps ──────────────────────────────────────────────────────────
if [ ! -d "frontend/node_modules" ]; then
  echo "→ Installing npm deps..."
  (cd frontend && npm install --silent)
fi

mkdir -p "$ROOT/logs"
PID_FILE="$ROOT/.platform.pids"
DASH_URL="http://localhost:5173"
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "your-ip")

# ── 4a. macOS Terminal tabs mode (default) ────────────────────────────────────
if ! $NO_TABS && [[ "$OSTYPE" == "darwin"* ]]; then
  BACKEND_CMD="cd '$ROOT/backend' && source '$ROOT/venv/bin/activate' && echo '🚀 Backend starting...' && python main.py"
  FRONTEND_CMD="cd '$ROOT/frontend' && echo '🎨 Frontend starting...' && npm run dev"

  osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  -- Reuse existing window or open new one
  if (count of windows) = 0 then
    do script "$BACKEND_CMD"
  else
    do script "$BACKEND_CMD" in front window
  end if
  delay 0.5
  tell application "System Events" to keystroke "t" using command down
  delay 0.3
  do script "$FRONTEND_CMD" in front window
end tell
APPLESCRIPT

  echo ""
  echo "============================================================"
  echo "  Two Terminal tabs opened:"
  echo "    Tab 1 → Backend  (python main.py)  port 5174"
  echo "    Tab 2 → Frontend (npm run dev)      port 5173"
  echo ""
  echo "  Dashboard: http://localhost:5173"
  echo "  API docs:  http://localhost:5174/docs"
  echo "============================================================"
  echo ""
  echo "  Opening dashboard in 8 seconds..."

  # Open browser once frontend is up
  (
    for _ in $(seq 1 40); do
      curl -s --max-time 1 "$DASH_URL" >/dev/null 2>&1 && break
      sleep 0.5
    done
    open "$DASH_URL"
  ) &
  exit 0
fi

# ── 4b. Background / --no-tabs mode ──────────────────────────────────────────
echo "→ Starting backend (python main.py)..."
(cd backend && python main.py > ../logs/backend.log 2>&1) &
BACKEND_PID=$!

echo "→ Starting frontend (npm run dev)..."
(cd frontend && npm run dev > ../logs/frontend.log 2>&1) &
FRONTEND_PID=$!

echo "$BACKEND_PID $FRONTEND_PID" > "$PID_FILE"

cleanup() {
  echo ""
  echo "Stopping platform..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
}
trap cleanup INT TERM EXIT

# Open browser once frontend is up
(
  for _ in $(seq 1 40); do
    curl -s --max-time 1 "$DASH_URL" >/dev/null 2>&1 && break
    sleep 0.5
  done
  if command -v open >/dev/null 2>&1; then open "$DASH_URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$DASH_URL"; fi
) &

echo ""
echo "============================================================"
echo "  Dashboard (local):   http://localhost:5173"
echo "  Dashboard (network): http://$LOCAL_IP:5173"
echo "  API (local):         http://localhost:5174/docs"
echo "  Logs: tail -f logs/backend.log  /  tail -f logs/frontend.log"
echo "  Press Ctrl+C to stop both."
echo "============================================================"

wait
