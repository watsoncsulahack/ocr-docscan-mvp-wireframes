#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${OCR_MVP_VENV:-/tmp/ocr-docscan-mvp-venv}"
PORT="${OCR_MVP_PORT:-8010}"
LOG="${OCR_MVP_LOG:-/tmp/ocr-docscan-backend.log}"
PID_FILE="${OCR_MVP_PID:-/tmp/ocr-docscan-backend.pid}"
RUNTIME_DIR="$ROOT_DIR/data/runtime"
LOCAL_URL_FILE="$RUNTIME_DIR/local_backend_url.txt"
DEFAULT_DB_PATH="$ROOT_DIR/data/records.sqlite"
ACTIVE_DB_FILE="$RUNTIME_DIR/active_db_path.txt"

REQ_BASE_DEFAULT="$ROOT_DIR/backend/requirements.txt"
REQ_BASE="${OCR_MVP_REQUIREMENTS_FILE:-$REQ_BASE_DEFAULT}"
REQ_LOCAL_OCR="$ROOT_DIR/backend/requirements-optional-local-ocr.txt"
REQ_DOCTR="$ROOT_DIR/backend/requirements-optional-doctr.txt"
REQ_MARKER="$VENV_DIR/.requirements.sha256"

INSTALL_LOCAL_OCR="${OCR_MVP_INSTALL_LOCAL_OCR:-0}"
INSTALL_DOCTR="${OCR_MVP_INSTALL_DOCTR:-0}"
SKIP_INSTALL="${OCR_MVP_SKIP_INSTALL:-0}"
CLEAN_DB="${OCR_MVP_CLEAN_DB:-0}"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

LLM_MODE="${OCR_MVP_LLM:-auto}"
case "$LLM_MODE" in
  ollama)
    export LLM_PROVIDER="openai"
    export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
    export LLM_MODEL="${LLM_MODEL:-${OCR_MVP_OLLAMA_MODEL:-glm-ocr}}"
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
    echo "[ocr-mvp] unknown OCR_MVP_LLM='$LLM_MODE' (use auto|ollama|gemini|openai)" >&2
    exit 1
    ;;
esac

is_termux=0
if [[ "${OCR_MVP_FORCE_TERMUX:-0}" == "1" ]] || [[ "${PREFIX:-}" == *"com.termux"* ]] || [[ -d "/data/data/com.termux" ]]; then
  is_termux=1
fi

mkdir -p "$(dirname "$LOG")"
mkdir -p "$RUNTIME_DIR"

if [[ "$CLEAN_DB" == "1" ]]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  CLEAN_DB_PATH="${OCR_MVP_CLEAN_DB_PATH:-$RUNTIME_DIR/records.clean.${stamp}.sqlite}"
  mkdir -p "$(dirname "$CLEAN_DB_PATH")"
  rm -f "$CLEAN_DB_PATH"
  export OCR_MVP_DB_PATH="$CLEAN_DB_PATH"
  echo "[ocr-mvp] clean DB requested; using disposable DB: $OCR_MVP_DB_PATH"
else
  export OCR_MVP_DB_PATH="${OCR_MVP_DB_PATH:-$DEFAULT_DB_PATH}"
fi

echo "$OCR_MVP_DB_PATH" > "$ACTIVE_DB_FILE"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "[ocr-mvp] creating venv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

if [[ "$is_termux" == "1" ]]; then
  if ! command -v rustc >/dev/null 2>&1 || ! command -v cargo >/dev/null 2>&1; then
    if command -v pkg >/dev/null 2>&1; then
      echo "[ocr-mvp] installing Termux Rust toolchain (required for pydantic-core)"
      pkg install -y rust clang pkg-config
    fi
  fi
  if ! command -v rustc >/dev/null 2>&1 || ! command -v cargo >/dev/null 2>&1; then
    echo "[ocr-mvp] ERROR: rustc/cargo missing. Run: pkg install -y rust clang pkg-config" >&2
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

  if [[ -z "${ANDROID_API_LEVEL:-}" ]] && command -v getprop >/dev/null 2>&1; then
    api_level="$(getprop ro.build.version.sdk 2>/dev/null || true)"
    if [[ "$api_level" =~ ^[0-9]+$ ]]; then
      export ANDROID_API_LEVEL="$api_level"
    fi
  fi
fi

calc_requirements_hash() {
  {
    cat "$REQ_BASE"
    echo "# install_local_ocr=$INSTALL_LOCAL_OCR"
    echo "# install_doctr=$INSTALL_DOCTR"
    if [[ "$INSTALL_LOCAL_OCR" == "1" ]] && [[ -f "$REQ_LOCAL_OCR" ]]; then
      cat "$REQ_LOCAL_OCR"
    fi
    if [[ "$INSTALL_DOCTR" == "1" ]] && [[ -f "$REQ_DOCTR" ]]; then
      cat "$REQ_DOCTR"
    fi
  } | sha256sum | awk '{print $1}'
}

if [[ "$SKIP_INSTALL" != "1" ]]; then
  req_hash="$(calc_requirements_hash)"
  old_hash=""
  if [[ -f "$REQ_MARKER" ]]; then
    old_hash="$(cat "$REQ_MARKER" 2>/dev/null || true)"
  fi

  need_install=0
  if [[ "$req_hash" != "$old_hash" ]]; then
    need_install=1
  fi
  if ! "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, pydantic" >/dev/null 2>&1; then
    need_install=1
  fi

  if [[ "$need_install" == "1" ]]; then
    echo "[ocr-mvp] installing dependencies from: $REQ_BASE"
    PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/pip" install --disable-pip-version-check --upgrade pip setuptools wheel maturin
    if ! PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/pip" install --disable-pip-version-check -r "$REQ_BASE"; then
      echo "[ocr-mvp] dependency install failed." >&2
      if [[ "$is_termux" == "1" ]]; then
        echo "[ocr-mvp] Termux hint: ensure rust toolchain is installed: pkg install -y rust clang pkg-config" >&2
        echo "[ocr-mvp] Termux hint: if this is Py3.13, keep CARGO_BUILD_TARGET set to android target." >&2
      fi
      exit 1
    fi
    if [[ "$INSTALL_LOCAL_OCR" == "1" ]] && [[ -f "$REQ_LOCAL_OCR" ]]; then
      echo "[ocr-mvp] installing optional local OCR deps"
      PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/pip" install --disable-pip-version-check -r "$REQ_LOCAL_OCR"
    fi
    if [[ "$INSTALL_DOCTR" == "1" ]] && [[ -f "$REQ_DOCTR" ]]; then
      echo "[ocr-mvp] installing optional DocTR deps"
      PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/pip" install --disable-pip-version-check -r "$REQ_DOCTR"
    fi
    echo "$req_hash" > "$REQ_MARKER"
  else
    echo "[ocr-mvp] dependency set unchanged, skipping pip install"
  fi
else
  echo "[ocr-mvp] OCR_MVP_SKIP_INSTALL=1, skipping dependency install"
fi

if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 0.3
  fi
fi

export ENABLE_LOCAL_CONTROL_API="${ENABLE_LOCAL_CONTROL_API:-1}"
nohup "$VENV_DIR/bin/uvicorn" backend.main:app --app-dir "$ROOT_DIR" --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
echo $! > "$PID_FILE"

ok=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.5
done

if [[ "$ok" != "1" ]]; then
  echo "Backend failed to start. See log: $LOG" >&2
  tail -n 120 "$LOG" >&2 || true
  exit 1
fi

if ! curl -fsS "http://127.0.0.1:${PORT}/records" >/dev/null 2>&1; then
  echo "Backend started but DB probe failed. See log: $LOG" >&2
  tail -n 120 "$LOG" >&2 || true
  exit 1
fi

echo "http://127.0.0.1:${PORT}" > "$LOCAL_URL_FILE"
echo "Backend running: http://127.0.0.1:${PORT}"
echo "DB probe: OK (/records)"
echo "OCR provider: ${OCR_PROVIDER:-auto}"
echo "LLM provider: ${LLM_PROVIDER:-openai}"
echo "PID: $(cat "$PID_FILE")"
echo "Log: $LOG"
