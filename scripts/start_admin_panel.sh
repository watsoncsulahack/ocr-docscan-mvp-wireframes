#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ADMIN_PANEL_PORT:-8091}"

echo "[admin-panel] starting on http://127.0.0.1:${PORT}/"
exec python3 "$ROOT_DIR/scripts/admin_panel_server.py" --port "$PORT"

