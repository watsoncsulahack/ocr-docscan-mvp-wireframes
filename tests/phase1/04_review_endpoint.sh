#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

sid="$(read_submission_id)"
payload='{
  "actor": "tester",
  "corrections": {
    "event_date": "04/26/2026"
  },
  "note": "Manual date correction during Phase 1 test"
}'

echo "POST $BASE_URL/review/$sid"
curl -sS -X POST "$BASE_URL/review/$sid" -H 'Content-Type: application/json' -d "$payload" | pretty
