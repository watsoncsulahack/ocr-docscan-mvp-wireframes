#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "GET $BASE_URL/health"
curl -sS "$BASE_URL/health" | pretty
