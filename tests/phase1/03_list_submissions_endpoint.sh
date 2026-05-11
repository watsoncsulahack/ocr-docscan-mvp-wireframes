#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "GET $BASE_URL/submissions"
curl -sS "$BASE_URL/submissions" | pretty

echo
echo "GET $BASE_URL/submissions?status=NEEDS_REVIEW"
curl -sS "$BASE_URL/submissions?status=NEEDS_REVIEW" | pretty
