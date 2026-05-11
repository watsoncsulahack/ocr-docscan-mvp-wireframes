#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

sid="$(read_submission_id)"
payload='{
  "actor": "admin-tester",
  "note": "Approved after manual review"
}'

echo "POST $BASE_URL/approve/$sid"
curl -sS -X POST "$BASE_URL/approve/$sid" -H 'Content-Type: application/json' -d "$payload" | pretty
