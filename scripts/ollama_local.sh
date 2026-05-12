#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-start}" # start | stop | status | pull | run

OLLAMA_BIN="${OCR_MVP_OLLAMA_BIN:-ollama}"
OLLAMA_PORT="${OCR_MVP_OLLAMA_PORT:-11434}"
OLLAMA_HOST="${OCR_MVP_OLLAMA_HOST:-127.0.0.1:${OLLAMA_PORT}}"
OLLAMA_URL="http://${OLLAMA_HOST}"
OLLAMA_MODEL="${OCR_MVP_OLLAMA_MODEL:-glm-ocr}"
OLLAMA_AUTO_PULL="${OCR_MVP_OLLAMA_AUTO_PULL:-1}"
OLLAMA_AUTO_RUN="${OCR_MVP_OLLAMA_AUTO_RUN:-1}"
OLLAMA_AUTO_INSTALL="${OCR_MVP_OLLAMA_INSTALL:-0}"
OLLAMA_WARM_PROMPT="${OCR_MVP_OLLAMA_WARM_PROMPT:-ok}"

LOCAL_DIR="$ROOT_DIR/.local"
PID_FILE="$LOCAL_DIR/ollama.pid"
LOG_FILE="$LOCAL_DIR/ollama.log"
mkdir -p "$LOCAL_DIR"

ensure_ollama_bin() {
  if command -v "$OLLAMA_BIN" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$OLLAMA_AUTO_INSTALL" == "1" ]]; then
    echo "[ollama] installing Ollama via official installer"
    if ! command -v curl >/dev/null 2>&1; then
      echo "[ollama] curl is required to auto-install ollama." >&2
      return 1
    fi

    if [[ "$(id -u)" == "0" ]]; then
      curl -fsSL https://ollama.com/install.sh | sh
    elif command -v sudo >/dev/null 2>&1; then
      curl -fsSL https://ollama.com/install.sh | sudo sh
    else
      echo "[ollama] install requires root or sudo. Install ollama manually or set OCR_MVP_OLLAMA_BIN." >&2
      return 1
    fi
  fi

  if ! command -v "$OLLAMA_BIN" >/dev/null 2>&1; then
    echo "[ollama] ollama binary not found." >&2
    echo "[ollama] install from https://ollama.com/download or set OCR_MVP_OLLAMA_INSTALL=1." >&2
    return 1
  fi
}

ollama_ready() {
  curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1
}

start_ollama() {
  ensure_ollama_bin

  if [[ -f "$PID_FILE" ]]; then
    local old
    old="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null && ollama_ready; then
      echo "[ollama] already running: ${OLLAMA_URL} (pid=$old)"
      return 0
    fi
  fi

  export OLLAMA_HOST="$OLLAMA_HOST"
  nohup "$OLLAMA_BIN" serve >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  local ok=0
  for _ in $(seq 1 80); do
    if ollama_ready; then
      ok=1
      break
    fi
    sleep 0.5
  done

  if [[ "$ok" != "1" ]]; then
    echo "[ollama] failed to start. Log: $LOG_FILE" >&2
    tail -n 120 "$LOG_FILE" >&2 || true
    return 1
  fi

  echo "[ollama] running: ${OLLAMA_URL} (pid=$(cat "$PID_FILE"))"

  if [[ "$OLLAMA_AUTO_PULL" == "1" ]] && [[ -n "$OLLAMA_MODEL" ]]; then
    echo "[ollama] ensuring model: $OLLAMA_MODEL"
    OLLAMA_HOST="$OLLAMA_HOST" "$OLLAMA_BIN" pull "$OLLAMA_MODEL"
  fi

  if [[ "$OLLAMA_AUTO_RUN" == "1" ]] && [[ -n "$OLLAMA_MODEL" ]]; then
    echo "[ollama] warming model with: ollama run $OLLAMA_MODEL"
    OLLAMA_HOST="$OLLAMA_HOST" "$OLLAMA_BIN" run "$OLLAMA_MODEL" "$OLLAMA_WARM_PROMPT" >/dev/null
  fi

  status_ollama
}

stop_ollama() {
  local stopped=0
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.2
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
      echo "[ollama] stopped managed ollama process (pid=$pid)"
      stopped=1
    fi
    rm -f "$PID_FILE"
  fi

  if [[ "$stopped" == "0" ]]; then
    echo "[ollama] no managed ollama process found"
  fi
}

status_ollama() {
  local pid=""
  [[ -f "$PID_FILE" ]] && pid="$(cat "$PID_FILE" 2>/dev/null || true)"

  if ollama_ready; then
    echo "[ollama] ready: ${OLLAMA_URL}${pid:+ (pid=$pid)}"
    if command -v "$OLLAMA_BIN" >/dev/null 2>&1; then
      OLLAMA_HOST="$OLLAMA_HOST" "$OLLAMA_BIN" list || true
    fi
    return 0
  fi

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "[ollama] process exists but API not ready yet (pid=$pid): ${OLLAMA_URL}"
    return 1
  fi

  echo "[ollama] not running: ${OLLAMA_URL}"
  return 1
}

pull_model() {
  ensure_ollama_bin
  if [[ -z "$OLLAMA_MODEL" ]]; then
    echo "[ollama] OCR_MVP_OLLAMA_MODEL is empty" >&2
    return 1
  fi
  OLLAMA_HOST="$OLLAMA_HOST" "$OLLAMA_BIN" pull "$OLLAMA_MODEL"
}

run_model() {
  ensure_ollama_bin
  if [[ -z "$OLLAMA_MODEL" ]]; then
    echo "[ollama] OCR_MVP_OLLAMA_MODEL is empty" >&2
    return 1
  fi
  OLLAMA_HOST="$OLLAMA_HOST" "$OLLAMA_BIN" run "$OLLAMA_MODEL" "$OLLAMA_WARM_PROMPT"
}

case "$ACTION" in
  start|up)
    start_ollama
    ;;
  stop|down)
    stop_ollama
    ;;
  status)
    status_ollama
    ;;
  pull)
    pull_model
    ;;
  run)
    run_model
    ;;
  *)
    echo "Usage: $(basename "$0") {start|stop|status|pull|run}" >&2
    exit 1
    ;;
esac
