#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${OCR_MVP_PORT:-8010}"
TUNNEL_LOG="${OCR_MVP_TUNNEL_LOG:-/tmp/ocr-docscan-tunnel.log}"
PID_FILE="${OCR_MVP_TUNNEL_PID:-/tmp/ocr-docscan-tunnel.pid}"
PAGES_URL="${OCR_MVP_PAGES_URL:-https://watsoncsulahack.github.io/ocr-docscan-mvp-wireframes/}"
FOLLOW_LOG="${OCR_MVP_FOLLOW_LOG:-0}"
ENV_FILE="$ROOT_DIR/.env"
RUNTIME_DIR="$ROOT_DIR/data/runtime"
PUBLIC_URL_FILE="$RUNTIME_DIR/public_backend_url.txt"
PUBLIC_URL_META_FILE="$RUNTIME_DIR/public_backend_url.meta"

mkdir -p "$RUNTIME_DIR"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

# Demo-friendly defaults (override by exporting your own values before running)
export OCR_PROVIDER="${OCR_PROVIDER:-ocrspace}"
if [[ -z "${LLM_PROVIDER:-}" ]]; then
  if [[ -n "${GEMINI_API_KEY:-}" || -n "${GOOGLE_API_KEY:-}" ]]; then
    export LLM_PROVIDER="gemini"
  else
    export LLM_PROVIDER="openai"
  fi
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh is required for localhost.run tunnel. Install openssh first." >&2
  exit 1
fi

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
for _ in $(seq 1 80); do
  if [[ -f "$TUNNEL_LOG" ]]; then
    URL="$(grep -Eo 'https://[A-Za-z0-9.-]+\.(lhr\.life|localhost\.run)' "$TUNNEL_LOG" | grep -v 'admin\.localhost\.run' | tail -n 1 || true)"
    if [[ -n "$URL" ]]; then
      break
    fi
  fi
  sleep 0.5
done

if [[ -z "$URL" ]]; then
  echo "Tunnel started but URL not detected yet."
  echo "Tunnel log: $TUNNEL_LOG"
else
  echo "$URL" > "$PUBLIC_URL_FILE"
  {
    echo "generatedAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "backendUrl=$URL"
    echo "frontendUrl=${PAGES_URL}?backend=${URL}"
  } > "$PUBLIC_URL_META_FILE"
  echo
  echo "Public backend URL: $URL"
  echo "Frontend URL (auto-wired): ${PAGES_URL}?backend=${URL}"
fi

echo
echo "OCR provider: ${OCR_PROVIDER}"
echo "LLM provider: ${LLM_PROVIDER}"
echo "Tunnel PID: $(cat "$PID_FILE")"
echo "Tunnel log: $TUNNEL_LOG"
echo "Stop later: bash $ROOT_DIR/scripts/stop_share_demo.sh"

if [[ "$FOLLOW_LOG" == "1" ]]; then
  echo
  echo "Following tunnel log. Press Ctrl+C to stop log view."
  tail -f "$TUNNEL_LOG"
fi
