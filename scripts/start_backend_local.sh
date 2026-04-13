#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${OCR_MVP_VENV:-/tmp/ocr-docscan-mvp-venv}"
PORT="${OCR_MVP_PORT:-8010}"
LOG="${OCR_MVP_LOG:-/tmp/ocr-docscan-backend.log}"
PID_FILE="${OCR_MVP_PID:-/tmp/ocr-docscan-backend.pid}"
RUNTIME_DIR="$ROOT_DIR/data/runtime"
LOCAL_URL_FILE="$RUNTIME_DIR/local_backend_url.txt"

REQ_BASE="$ROOT_DIR/backend/requirements.txt"
REQ_LOCAL_OCR="$ROOT_DIR/backend/requirements-optional-local-ocr.txt"
REQ_DOCTR="$ROOT_DIR/backend/requirements-optional-doctr.txt"
REQ_MARKER="$VENV_DIR/.requirements.sha256"

INSTALL_LOCAL_OCR="${OCR_MVP_INSTALL_LOCAL_OCR:-0}"
INSTALL_DOCTR="${OCR_MVP_INSTALL_DOCTR:-0}"
SKIP_INSTALL="${OCR_MVP_SKIP_INSTALL:-0}"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

mkdir -p "$(dirname "$LOG")"
mkdir -p "$RUNTIME_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "[ocr-mvp] creating venv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
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
    echo "[ocr-mvp] installing dependencies"
    PIP_NO_CACHE_DIR=1 "$VENV_DIR/bin/pip" install --disable-pip-version-check -r "$REQ_BASE"
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
