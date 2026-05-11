#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${OCR_MVP_BACKEND_PORT:-8010}"
FRONTEND_PORT="${OCR_MVP_FRONTEND_PORT:-8080}"

stopped=0

kill_pid_file() {
  local file="$1"
  local name="$2"
  if [[ ! -f "$file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.2
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "[stop-mvp] stopped $name (pid=$pid)"
    stopped=1
  fi
  rm -f "$file"
}

kill_tmux_session() {
  local name="$1"
  if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$name" 2>/dev/null; then
    tmux kill-session -t "$name" || true
    echo "[stop-mvp] stopped tmux session: $name"
    stopped=1
  fi
}

kill_listening_port() {
  local port="$1"
  local label="$2"
  local pids=""

  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti TCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)"
  fi

  for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
      echo "[stop-mvp] stopped $label listener on :$port (pid=$pid)"
      stopped=1
    fi
  done
}

kill_by_pattern() {
  local pattern="$1"
  local label="$2"
  local pids=""
  pids="$(ps -ef | grep -E "$pattern" | grep -v grep | awk '{print $2}' | sort -u || true)"
  for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
      echo "[stop-mvp] stopped $label (pid=$pid)"
      stopped=1
    fi
  done
}

kill_tmux_session "ocr-backend"
kill_tmux_session "ocr-frontend"

kill_pid_file "$ROOT_DIR/.local/backend_launcher.pid" "backend launcher"
kill_pid_file "$ROOT_DIR/.local/frontend.pid" "frontend server"
kill_pid_file "/tmp/ocr-docscan-backend.pid" "backend uvicorn"

kill_listening_port "$BACKEND_PORT" "backend"
kill_listening_port "$FRONTEND_PORT" "frontend"

kill_by_pattern "uvicorn .*--port ${BACKEND_PORT}" "backend (pattern)"
kill_by_pattern "python3 -m http\.server ${FRONTEND_PORT}" "frontend (pattern)"
kill_by_pattern "tmux .* -s ocr-backend" "tmux backend launcher"
kill_by_pattern "tmux .* -s ocr-frontend" "tmux frontend launcher"

if [[ "$stopped" == "0" ]]; then
  echo "[stop-mvp] no running MVP server processes found"
else
  echo "[stop-mvp] done"
fi
