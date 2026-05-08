#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "[phase5] review workflow lifecycle on $BASE_URL"

SUFFIX="$(date +%s)-$RANDOM"
CONTAINER="TSTU${SUFFIX:0:7}"

submit_payload=$(cat <<JSON
{
  "sourceFileName": "phase5-$SUFFIX.pdf",
  "fileType": "pdf",
  "classifier": "container",
  "extracted": {
    "container_number": "$CONTAINER",
    "event_date": "05/08/2026"
  },
  "confidence": {
    "container_number": 0.95,
    "event_date": 0.2
  }
}
JSON
)

submit_resp="$(curl -sS -X POST "$BASE_URL/submit" -H 'Content-Type: application/json' -d "$submit_payload")"
echo "$submit_resp" | python3 -m json.tool

submission_id="$(echo "$submit_resp" | python3 -c 'import json,sys;print(json.load(sys.stdin)["submissionId"])')"
status="$(echo "$submit_resp" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')"
[[ "$status" == "NEEDS_REVIEW" ]] || { echo "expected NEEDS_REVIEW after low confidence, got $status"; exit 1; }

review_payload='{"actor":"phase5-tester","note":"manual correction","corrections":{"event_date":"05/09/2026"}}'
review_resp="$(curl -sS -X POST "$BASE_URL/review/$submission_id" -H 'Content-Type: application/json' -d "$review_payload")"
echo "$review_resp" | python3 -m json.tool

approve_payload='{"actor":"phase5-admin","note":"approved in phase5 test"}'
approve_resp="$(curl -sS -X POST "$BASE_URL/approve/$submission_id" -H 'Content-Type: application/json' -d "$approve_payload")"
echo "$approve_resp" | python3 -m json.tool

bundle="$(curl -sS "$BASE_URL/submission/$submission_id")"
echo "$bundle" | python3 -m json.tool >/tmp/phase5-bundle.json

python3 - <<'PY' "$bundle"
import json,sys
obj=json.loads(sys.argv[1])
assert obj["submission"]["status"]=="APPROVED"
reviews=obj.get("reviewTasks") or []
assert reviews, "expected review task"
assert reviews[0]["status"]=="RESOLVED", reviews[0]
assert reviews[0].get("assigned_to") in ("phase5-tester", "phase5-admin", "admin", "user"), reviews[0]
actions=[a.get("action") for a in (obj.get("audit") or [])]
for needed in ("SUBMIT","REVIEW_EDIT","APPROVE"):
    assert needed in actions, (needed, actions)
print("PASS")
PY

echo "[phase5] lifecycle checks passed"
