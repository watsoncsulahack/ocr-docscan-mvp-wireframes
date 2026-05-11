#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible wrapper to the universal bootstrap.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/bootstrap_mvp.sh" "$@"
