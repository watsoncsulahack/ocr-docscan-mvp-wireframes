#!/usr/bin/env bash
set -euo pipefail

TPID_FILE="${OCR_MVP_TUNNEL_PID:-/tmp/ocr-docscan-tunnel.pid}"
if [[ -f "$TPID_FILE" ]]; then
  tpid="$(cat "$TPID_FILE" 2>/dev/null || true)"
  if [[ -n "$tpid" ]] && kill -0 "$tpid" 2>/dev/null; then
    kill "$tpid" 2>/dev/null || true
    echo "Stopped tunnel PID $tpid"
  else
    echo "No running tunnel process found"
  fi
  rm -f "$TPID_FILE"
else
  echo "No tunnel PID file found"
fi

bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stop_backend_local.sh"
