#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

ACTION="up"                      # up | share | down
PROFILE="${OCR_MVP_PROFILE:-auto}" # auto | phone | laptop
SHARE="${OCR_MVP_SHARE:-0}"        # 0 | 1
LOCAL_OCR="${OCR_MVP_LOCAL_OCR:-0}" # 0 | 1
DOCTR="${OCR_MVP_DOCTR:-0}"         # 0 | 1
LLM="${OCR_MVP_LLM:-auto}"          # auto | ollama | gemini | openai
CLEAN_DB="${OCR_MVP_CLEAN_DB:-0}"   # 0 | 1

usage() {
  cat <<EOF
Usage: ./scripts/run_dev.sh [up|share|down] [--clean]

Options:
  --clean   start backend with a clean DB
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      up|share|down)
        ACTION="$1"
        ;;
      --clean)
        CLEAN_DB=1
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        echo "Unknown arg: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done
}

parse_args "$@"
export OCR_MVP_CLEAN_DB="$CLEAN_DB"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

is_termux=0
if [[ "${PREFIX:-}" == *"com.termux"* ]] || [[ -d "/data/data/com.termux" ]]; then
  is_termux=1
fi

if [[ "$PROFILE" == "auto" ]]; then
  if [[ "$is_termux" == "1" ]]; then
    PROFILE="phone"
  else
    PROFILE="laptop"
  fi
fi

case "$PROFILE" in
  phone)
    export OCR_MVP_PORT="${OCR_MVP_PORT:-8010}"
    export OCR_MVP_INSTALL_LOCAL_OCR="${OCR_MVP_INSTALL_LOCAL_OCR:-$LOCAL_OCR}"
    export OCR_MVP_INSTALL_DOCTR="${OCR_MVP_INSTALL_DOCTR:-0}"
    ;;
  laptop)
    export OCR_MVP_PORT="${OCR_MVP_PORT:-8010}"
    export OCR_MVP_INSTALL_LOCAL_OCR="${OCR_MVP_INSTALL_LOCAL_OCR:-$LOCAL_OCR}"
    export OCR_MVP_INSTALL_DOCTR="${OCR_MVP_INSTALL_DOCTR:-$DOCTR}"
    ;;
  *)
    echo "Unknown profile: $PROFILE (use auto|phone|laptop)" >&2
    exit 1
    ;;
esac

case "$LLM" in
  ollama)
    export LLM_PROVIDER="openai"
    export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
    ;;
  gemini)
    export LLM_PROVIDER="gemini"
    ;;
  openai)
    export LLM_PROVIDER="openai"
    ;;
  auto)
    ;;
  *)
    echo "Unknown LLM mode: $LLM (use auto|ollama|gemini|openai)" >&2
    exit 1
    ;;
esac

if [[ "$ACTION" == "down" ]]; then
  bash "$ROOT_DIR/scripts/stop_share_demo.sh"
  bash "$ROOT_DIR/scripts/stop_mvp.sh"
  exit 0
fi

if [[ "$ACTION" == "share" ]]; then
  export OCR_MVP_SHARE=1
  SHARE=1
fi

if [[ "$ACTION" != "down" ]] && [[ "$LLM" == "ollama" ]] && [[ -x "$ROOT_DIR/scripts/ollama_local.sh" ]]; then
  bash "$ROOT_DIR/scripts/ollama_local.sh" start
fi

if [[ "$SHARE" == "1" ]]; then
  bash "$ROOT_DIR/scripts/share_demo_no_account.sh"
else
  bash "$ROOT_DIR/scripts/start_backend_local.sh"
fi

echo ""
echo "[run-dev] action=$ACTION profile=$PROFILE share=$SHARE clean_db=$CLEAN_DB local_ocr=${OCR_MVP_INSTALL_LOCAL_OCR:-0} doctr=${OCR_MVP_INSTALL_DOCTR:-0} llm=$LLM"
