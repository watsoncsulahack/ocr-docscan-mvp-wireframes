#!/usr/bin/env bash
set -euo pipefail
PID_FILE="${OCR_MVP_PID:-/tmp/ocr-docscan-backend.pid}"
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "Stopped backend PID $pid"
  else
    echo "No running backend process found"
  fi
  rm -f "$PID_FILE"
else
  echo "No PID file found"
fi
