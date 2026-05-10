#!/usr/bin/env bash
set -euo pipefail

# One-shot bootstrap for vanilla Android + Termux + tmux.
# - Installs required packages
# - Clones/updates repo
# - Creates venv + installs Python deps
# - Starts backend + frontend in tmux sessions

REPO_URL="${OCR_MVP_REPO_URL:-https://github.com/watsoncsulahack/ocr-docscan-mvp-wireframes.git}"
REPO_DIR="${OCR_MVP_REPO_DIR:-$HOME/ocr-docscan-mvp-wireframes}"
BACKEND_PORT="${OCR_MVP_BACKEND_PORT:-8010}"
FRONTEND_PORT="${OCR_MVP_FRONTEND_PORT:-8080}"
PROFILE="${OCR_MVP_PROFILE:-phone}"
LLM="${OCR_MVP_LLM:-auto}"

echo "[bootstrap-android] installing Termux packages"
if command -v pkg >/dev/null 2>&1; then
  pkg update -y
  pkg install -y git python tmux curl
else
  echo "[bootstrap-android] 'pkg' not found; this script is intended for Termux." >&2
  exit 1
fi

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "[bootstrap-android] cloning repo to $REPO_DIR"
  git clone "$REPO_URL" "$REPO_DIR"
else
  echo "[bootstrap-android] updating existing repo at $REPO_DIR"
  git -C "$REPO_DIR" fetch --all --prune
  git -C "$REPO_DIR" pull --ff-only || true
fi

cd "$REPO_DIR"

if [[ ! -d .venv ]]; then
  echo "[bootstrap-android] creating venv"
  python -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

echo "[bootstrap-android] stopping old tmux sessions (if any)"
tmux kill-session -t ocr-backend 2>/dev/null || true
tmux kill-session -t ocr-frontend 2>/dev/null || true

echo "[bootstrap-android] starting backend session: ocr-backend"
tmux new-session -d -s ocr-backend "cd '$REPO_DIR' && source .venv/bin/activate && OCR_MVP_PROFILE='$PROFILE' OCR_MVP_LLM='$LLM' OCR_MVP_PORT='$BACKEND_PORT' bash ./scripts/run_dev.sh up"

echo "[bootstrap-android] starting frontend session: ocr-frontend"
tmux new-session -d -s ocr-frontend "cd '$REPO_DIR' && python -m http.server '$FRONTEND_PORT'"

sleep 2

HEALTH_URL="http://127.0.0.1:${BACKEND_PORT}/health"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
ADMIN_URL="${FRONTEND_URL}/admin.html"
ADMIN_MOCK_URL="${FRONTEND_URL}/admin.html?mockdb=1"

echo ""
echo "[bootstrap-android] quick checks"
if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "✅ Backend healthy: $HEALTH_URL"
else
  echo "⚠️ Backend not healthy yet: $HEALTH_URL"
  echo "   Check logs: tmux attach -t ocr-backend"
fi

echo "✅ Frontend URL: $FRONTEND_URL"
echo "✅ Admin URL: $ADMIN_URL"
echo "✅ Admin mock URL: $ADMIN_MOCK_URL"
echo ""
echo "tmux sessions:"
tmux ls | grep -E 'ocr-backend|ocr-frontend' || true

echo ""
echo "Attach logs:"
echo "  tmux attach -t ocr-backend"
echo "  tmux attach -t ocr-frontend"
echo "Detach from tmux: Ctrl-b then d"
