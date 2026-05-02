#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

payload='{
  "sourceFileName": "Container Drop Ticket.pdf",
  "fileType": "pdf",
  "classifier": "container",
  "originalFileName": "Container Drop Ticket.pdf",
  "extracted": {
    "container_number": "ABCD1234567",
    "event_date": ""
  },
  "confidence": {
    "container_number": 0.98,
    "event_date": 0.40
  }
}'

echo "POST $BASE_URL/submit"
resp=$(curl -sS -X POST "$BASE_URL/submit" -H 'Content-Type: application/json' -d "$payload")
echo "$resp" | pretty

echo -n "Saved submissionId: "
save_submission_id "$resp"
