#!/usr/bin/env bash
#
# stop.sh — Stop the Multi-Agent Auto-Scheduling Platform.
#
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/.platform.pids"

if [ -f "$PID_FILE" ]; then
  read -r BACKEND_PID FRONTEND_PID < "$PID_FILE"
  echo "==> Stopping backend (PID $BACKEND_PID) and frontend (PID $FRONTEND_PID)..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "    Done."
else
  echo "==> No running platform found (.platform.pids missing)."
  echo "    Attempting to kill any uvicorn/vite processes..."
  pkill -f "uvicorn main:app" 2>/dev/null || true
  pkill -f "vite" 2>/dev/null || true
  echo "    Done."
fi
