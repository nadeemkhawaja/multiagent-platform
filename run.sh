#!/usr/bin/env bash
#
# run.sh — Launch the Multi-Agent Auto-Scheduling Platform (backend + frontend).
# Stops both cleanly on Ctrl+C.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "==> Multi-Agent Platform launcher"

# 1. Check Ollama is reachable
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
if curl -s --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "    Ollama: OK ($OLLAMA_URL)"
else
  echo "    WARNING: Ollama not reachable at $OLLAMA_URL."
  echo "             Start it (the Ollama app or 'ollama serve') and run: ollama pull qwen3.5:4b"
fi

# 2. Python virtual environment + backend deps
# Prefer Python 3.12 (matches pinned dependency wheels). Fall back to python3.
if command -v python3.12 >/dev/null 2>&1; then
  PYTHON=python3.12
else
  PYTHON=python3
  echo "    NOTE: python3.12 not found, using $($PYTHON --version). Pinned deps may not have wheels."
fi

# Rebuild the venv if it's missing or was created with a different interpreter.
if [ -d "venv" ] && ! venv/bin/python --version 2>/dev/null | grep -q "3.12"; then
  echo "==> Existing venv is not Python 3.12 — recreating it..."
  rm -rf venv
fi
if [ ! -d "venv" ]; then
  echo "==> Creating Python virtual environment with $PYTHON ..."
  "$PYTHON" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
echo "==> Installing/refreshing backend dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 3. Frontend deps
if [ ! -d "frontend/node_modules" ]; then
  echo "==> Installing frontend dependencies..."
  (cd frontend && npm install)
fi

# 4. Start backend
echo "==> Starting backend on http://localhost:5174 ..."
(cd backend && uvicorn main:app --reload --port 5174) &
BACKEND_PID=$!

# 5. Start frontend
echo "==> Starting frontend on http://localhost:5173 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

# Clean shutdown of both children on exit
cleanup() {
  echo ""
  echo "==> Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo ""
echo "============================================================"
echo "  Dashboard:  http://localhost:5173"
echo "  API:        http://localhost:5174/docs"
echo "  Press Ctrl+C to stop both."
echo "============================================================"

wait
