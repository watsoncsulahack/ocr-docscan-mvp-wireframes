#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible wrapper: Android/Termux defaults.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OCR_MVP_PROFILE="${OCR_MVP_PROFILE:-phone}"
export OCR_MVP_USE_TMUX="${OCR_MVP_USE_TMUX:-1}"

exec bash "$SCRIPT_DIR/bootstrap_mvp.sh" "$@"
