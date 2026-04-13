#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${OCR_MVP_VENV:-/tmp/ocr-docscan-mvp-venv}"
PORT="${OCR_MVP_PORT:-8010}"
LOG="${OCR_MVP_LOG:-/tmp/ocr-docscan-backend.log}"
PID_FILE="${OCR_MVP_PID:-/tmp/ocr-docscan-backend.pid}"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" -q install -r "$ROOT_DIR/backend/requirements.txt"

if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 0.3
  fi
fi

nohup "$VENV_DIR/bin/uvicorn" backend.main:app --app-dir "$ROOT_DIR" --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
echo $! > "$PID_FILE"

ok=0
for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.5
done
if [[ "$ok" != "1" ]]; then
  echo "Backend failed to start. See log: $LOG" >&2
  exit 1
fi

echo "Backend running: http://127.0.0.1:${PORT}"
echo "PID: $(cat "$PID_FILE")"
