#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "GET $BASE_URL/admin/flagged"
curl -sS "$BASE_URL/admin/flagged" | pretty
