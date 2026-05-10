#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROFILE="${OCR_MVP_PROFILE:-auto}"   # auto | phone | laptop
LLM="${OCR_MVP_LLM:-auto}"           # auto | gemini | openai | ollama
SHARE="${OCR_MVP_SHARE:-0}"          # 0 | 1

echo "[bootstrap] repo: $ROOT_DIR"

if [[ ! -f "$ROOT_DIR/backend/requirements.txt" ]]; then
  echo "[bootstrap] backend/requirements.txt not found. Run inside cloned repo." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[bootstrap] python3 is required." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "[bootstrap] git is required." >&2
  exit 1
fi

echo "[bootstrap] python: $(python3 --version 2>/dev/null || true)"
echo "[bootstrap] git: $(git --version 2>/dev/null || true)"

if [[ ! -d .venv ]]; then
  echo "[bootstrap] creating virtualenv (.venv)"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
pip install -r backend/requirements.txt >/dev/null

echo "[bootstrap] dependencies installed"

echo "[bootstrap] starting MVP via scripts/run_dev.sh up"
OCR_MVP_PROFILE="$PROFILE" OCR_MVP_LLM="$LLM" OCR_MVP_SHARE="$SHARE" bash "$ROOT_DIR/scripts/run_dev.sh" up

PORT="${OCR_MVP_PORT:-8010}"
BACKEND_URL="http://127.0.0.1:${PORT}"
HEALTH_URL="${BACKEND_URL}/health"
FRONTEND_URL="http://127.0.0.1:8080"

echo ""
echo "[bootstrap] checking backend health: $HEALTH_URL"
if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "[bootstrap] backend OK"
else
  echo "[bootstrap] backend health check failed (it may still be starting)"
fi

echo ""
echo "[bootstrap] next steps"
echo "1) Start frontend static server in another terminal:"
echo "   cd $ROOT_DIR && python3 -m http.server 8080"
echo "2) Open frontend: $FRONTEND_URL"
echo "3) Open backend health: $HEALTH_URL"
echo "4) Admin (mock DB): $FRONTEND_URL/admin.html?mockdb=1"

if [[ "$SHARE" == "1" ]]; then
  echo ""
  echo "[bootstrap] share mode enabled; check output above for public backend URL"
fi
