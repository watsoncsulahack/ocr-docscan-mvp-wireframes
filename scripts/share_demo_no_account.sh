#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${OCR_MVP_PORT:-8010}"
TUNNEL_LOG="${OCR_MVP_TUNNEL_LOG:-/tmp/ocr-docscan-tunnel.log}"
PID_FILE="${OCR_MVP_TUNNEL_PID:-/tmp/ocr-docscan-tunnel.pid}"
PAGES_URL="${OCR_MVP_PAGES_URL:-https://watsoncsulahack.github.io/ocr-docscan-mvp-wireframes/}"

bash "$ROOT_DIR/scripts/start_backend_local.sh"

if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 0.3
  fi
fi

: > "$TUNNEL_LOG"
nohup ssh \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -R 80:127.0.0.1:${PORT} \
  nokey@localhost.run >"$TUNNEL_LOG" 2>&1 &

echo $! > "$PID_FILE"

URL=""
for _ in $(seq 1 60); do
  if [[ -f "$TUNNEL_LOG" ]]; then
    URL="$(grep -Eo 'https://[A-Za-z0-9.-]+\.lhr\.life' "$TUNNEL_LOG" | tail -n 1 || true)"
    if [[ -z "$URL" ]]; then
      URL="$(grep -Eo 'https://[A-Za-z0-9.-]+\.localhost\.run' "$TUNNEL_LOG" | tail -n 1 || true)"
      if [[ "$URL" == "https://admin.localhost.run" ]]; then
        URL=""
      fi
    fi
    if [[ -n "$URL" ]]; then
      break
    fi
  fi
  sleep 0.5
done

if [[ -z "$URL" ]]; then
  echo "Tunnel started but URL not detected yet. Log: $TUNNEL_LOG"
else
  echo "\nPublic backend URL: $URL"
  echo "Frontend URL (auto-wired): ${PAGES_URL}?backend=${URL}"
fi

echo "\nTunnel is running. Press Ctrl+C to stop viewing logs."
echo "To stop later: bash $ROOT_DIR/scripts/stop_share_demo.sh"

tail -f "$TUNNEL_LOG"
