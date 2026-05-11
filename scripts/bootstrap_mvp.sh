#!/usr/bin/env bash
set -euo pipefail

# Universal OCR MVP bootstrap (Termux + Linux/macOS)
# - Installs base dependencies when possible
# - Clones/updates repo (optional)
# - Creates venv and installs backend deps
# - Starts backend + frontend (admin panel is /admin.html)

REPO_URL="${OCR_MVP_REPO_URL:-https://github.com/watsoncsulahack/ocr-docscan-mvp-wireframes.git}"
REPO_DIR="${OCR_MVP_REPO_DIR:-$HOME/ocr-docscan-mvp-wireframes}"
BACKEND_PORT="${OCR_MVP_BACKEND_PORT:-8010}"
FRONTEND_PORT="${OCR_MVP_FRONTEND_PORT:-8080}"
PROFILE="${OCR_MVP_PROFILE:-auto}"   # auto | phone | laptop
LLM="${OCR_MVP_LLM:-auto}"           # auto | ollama | gemini | openai
USE_TMUX="${OCR_MVP_USE_TMUX:-1}"    # 1 | 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

is_termux=0
if [[ "${PREFIX:-}" == *"com.termux"* ]] || [[ -d "/data/data/com.termux" ]]; then
  is_termux=1
fi

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_base_deps() {
  local need=0
  ensure_cmd git || need=1
  ensure_cmd python3 || need=1
  ensure_cmd curl || need=1
  if [[ "$is_termux" == "1" ]]; then
    ensure_cmd rustc || need=1
    ensure_cmd cargo || need=1
    ensure_cmd pkg-config || need=1
    ensure_cmd clang || need=1
  fi
  if [[ "$USE_TMUX" == "1" ]]; then
    ensure_cmd tmux || need=1
  fi
  [[ "$need" == "0" ]] && return 0

  echo "[bootstrap-mvp] installing missing system packages"
  if [[ "$is_termux" == "1" ]] && ensure_cmd pkg; then
    pkg update -y
    pkg install -y git python tmux curl rust clang pkg-config
    return 0
  fi

  if ensure_cmd apt-get; then
    if [[ "$(id -u)" == "0" ]]; then
      apt-get update -y
      apt-get install -y git python3 python3-venv python3-pip tmux curl
    elif ensure_cmd sudo; then
      sudo apt-get update -y
      sudo apt-get install -y git python3 python3-venv python3-pip tmux curl
    else
      echo "[bootstrap-mvp] install needed but no root/sudo available." >&2
      echo "Install manually: git python3 python3-venv python3-pip tmux curl" >&2
      exit 1
    fi
    return 0
  fi

  if ensure_cmd brew; then
    brew install git python tmux curl
    return 0
  fi

  echo "[bootstrap-mvp] unsupported package manager for auto-install." >&2
  echo "Install manually: git python3 venv pip tmux curl" >&2
  exit 1
}

resolve_repo_root() {
  if [[ -f "$SCRIPT_ROOT/backend/requirements.txt" ]]; then
    echo "$SCRIPT_ROOT"
    return 0
  fi

  if [[ ! -d "$REPO_DIR/.git" ]]; then
    echo "[bootstrap-mvp] cloning repo to $REPO_DIR"
    git clone "$REPO_URL" "$REPO_DIR"
  else
    echo "[bootstrap-mvp] updating existing repo at $REPO_DIR"
    git -C "$REPO_DIR" fetch --all --prune
    git -C "$REPO_DIR" pull --ff-only || true
  fi
  echo "$REPO_DIR"
}

start_with_tmux() {
  local root="$1"
  tmux kill-session -t ocr-backend 2>/dev/null || true
  tmux kill-session -t ocr-frontend 2>/dev/null || true

  tmux new-session -d -s ocr-backend \
    "cd '$root' && source .venv/bin/activate && OCR_MVP_PROFILE='$PROFILE' OCR_MVP_LLM='$LLM' OCR_MVP_PORT='$BACKEND_PORT' OCR_MVP_VENV='$root/.venv' bash ./scripts/start_backend_local.sh"

  tmux new-session -d -s ocr-frontend \
    "cd '$root' && python3 -m http.server '$FRONTEND_PORT' --bind 127.0.0.1"
}

start_without_tmux() {
  local root="$1"
  mkdir -p "$root/.local"
  local backend_log="$root/.local/backend.log"
  local frontend_log="$root/.local/frontend.log"
  local backend_pid="$root/.local/backend_launcher.pid"
  local frontend_pid="$root/.local/frontend.pid"

  if [[ -f "$frontend_pid" ]] && kill -0 "$(cat "$frontend_pid" 2>/dev/null || true)" 2>/dev/null; then
    kill "$(cat "$frontend_pid")" 2>/dev/null || true
  fi

  (
    cd "$root"
    source .venv/bin/activate
    OCR_MVP_PROFILE="$PROFILE" OCR_MVP_LLM="$LLM" OCR_MVP_PORT="$BACKEND_PORT" OCR_MVP_VENV="$root/.venv" \
      bash ./scripts/start_backend_local.sh
  ) >"$backend_log" 2>&1 &
  echo $! > "$backend_pid"

  (
    cd "$root"
    python3 -m http.server "$FRONTEND_PORT" --bind 127.0.0.1
  ) >"$frontend_log" 2>&1 &
  echo $! > "$frontend_pid"
}

main() {
  echo "[bootstrap-mvp] preparing environment"
  install_base_deps

  local root
  root="$(resolve_repo_root)"
  cd "$root"

  echo "[bootstrap-mvp] repo: $root"
  echo "[bootstrap-mvp] python=$(python3 --version 2>/dev/null | tr -d '\n') termux=$is_termux"
  echo "[bootstrap-mvp] requirements=backend/requirements.txt"

  if [[ "$is_termux" == "1" ]]; then
    if ! ensure_cmd rustc || ! ensure_cmd cargo; then
      echo "[bootstrap-mvp] ERROR: rustc/cargo missing after dependency install." >&2
      echo "Run: pkg install -y rust clang pkg-config" >&2
      exit 1
    fi
    if [[ -z "${CARGO_BUILD_TARGET:-}" ]]; then
      arch="$(uname -m || true)"
      case "$arch" in
        aarch64|arm64) export CARGO_BUILD_TARGET="aarch64-linux-android" ;;
        armv7l|armv8l) export CARGO_BUILD_TARGET="armv7-linux-androideabi" ;;
        x86_64|amd64) export CARGO_BUILD_TARGET="x86_64-linux-android" ;;
      esac
    fi
  fi

  [[ -d .venv ]] || python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip >/dev/null
  pip install --upgrade setuptools wheel maturin >/dev/null
  pip install -r backend/requirements.txt >/dev/null

  if [[ "$USE_TMUX" == "1" ]] && ensure_cmd tmux; then
    start_with_tmux "$root"
  else
    start_without_tmux "$root"
  fi

  local health_url="http://127.0.0.1:${BACKEND_PORT}/health"
  local frontend_url="http://127.0.0.1:${FRONTEND_PORT}"
  local ok=0
  for _ in $(seq 1 40); do
    if curl -fsS "$health_url" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 0.5
  done

  echo ""
  if [[ "$ok" == "1" ]]; then
    echo "✅ Backend healthy: $health_url"
  else
    echo "⚠️ Backend still starting: $health_url"
    if [[ -f "$root/.local/backend.log" ]]; then
      echo "[bootstrap-mvp] tail backend log:"
      tail -n 30 "$root/.local/backend.log" || true
    fi
  fi
  echo "✅ Frontend: $frontend_url"
  echo "✅ Admin panel: $frontend_url/admin.html"
  echo "✅ Admin panel (mock DB): $frontend_url/admin.html?mockdb=1"

  if [[ "$USE_TMUX" == "1" ]] && ensure_cmd tmux; then
    echo ""
    echo "tmux sessions:"
    tmux ls | grep -E 'ocr-backend|ocr-frontend' || true
    echo "Attach logs: tmux attach -t ocr-backend"
  fi
}

main "$@"
