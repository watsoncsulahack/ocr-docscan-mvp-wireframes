#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

sid="$(read_submission_id)"
echo "GET $BASE_URL/submission/$sid"
curl -sS "$BASE_URL/submission/$sid" | pretty
