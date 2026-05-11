#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "[phase4] checking rules matrix against $BASE_URL"

post_json() {
  local payload="$1"
  curl -sS -X POST "$BASE_URL/submit" -H 'Content-Type: application/json' -d "$payload"
}

assert_case() {
  local name="$1"
  local payload="$2"
  local pycheck="$3"
  echo "\n== $name =="
  local resp
  resp="$(post_json "$payload")"
  echo "$resp" | python3 -m json.tool
  python3 - "$pycheck" "$resp" <<'PY'
import json,sys
check=sys.argv[1]
obj=json.loads(sys.argv[2])
ns={"obj":obj}
ok=eval(check,{},ns)
if not ok:
    raise SystemExit(f"assertion failed: {check}")
print("PASS")
PY
}

assert_case \
  "unsupported_document_rule" \
  '{"sourceFileName":"u1.pdf","fileType":"pdf","classifier":"other","extracted":{},"confidence":{}}' \
  'obj["status"]=="NEEDS_REVIEW" and any(r["rule_id"]=="unsupported_document_rule" and (not r["passed"]) for r in obj["ruleResults"])'

assert_case \
  "missing_data_rule" \
  '{"sourceFileName":"u2.pdf","fileType":"pdf","classifier":"container","extracted":{"container_number":"","event_date":""},"confidence":{"container_number":0.9,"event_date":0.9}}' \
  'obj["status"]=="NEEDS_REVIEW" and any(r["rule_id"]=="required_field_rule" and (not r["passed"]) for r in obj["ruleResults"]) and any(r["rule_id"]=="missing_data_rule" and (not r["passed"]) for r in obj["ruleResults"])'

assert_case \
  "confidence_threshold_rule" \
  '{"sourceFileName":"u3.pdf","fileType":"pdf","classifier":"container","extracted":{"container_number":"ABCD1234567","event_date":"05/05/2026"},"confidence":{"container_number":0.95,"event_date":0.2}}' \
  'obj["status"]=="NEEDS_REVIEW" and any(r["rule_id"]=="confidence_threshold_rule" and (not r["passed"]) for r in obj["ruleResults"])'

payload_dup='{"sourceFileName":"u4.pdf","fileType":"pdf","classifier":"container","extracted":{"container_number":"ABCD1234567","event_date":"05/05/2026"},"confidence":{"container_number":0.95,"event_date":0.95}}'
first="$(post_json "$payload_dup")"
second="$(post_json "$payload_dup")"
echo "\n== duplicate_detection_rule =="
echo "$second" | python3 -m json.tool
python3 - "$second" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
assert obj["status"]=="DUPLICATE"
assert any(r["rule_id"]=="duplicate_detection_rule" and (not r["passed"]) for r in obj["ruleResults"])
print("PASS")
PY

assert_case \
  "audit_rule_present" \
  '{"sourceFileName":"u5.pdf","fileType":"pdf","classifier":"container","extracted":{"container_number":"XYZU1234567","event_date":"05/05/2026"},"confidence":{"container_number":0.95,"event_date":0.95}}' \
  'any(r["rule_id"]=="audit_rule" and r["passed"] for r in obj["ruleResults"])'

echo "\n[phase4] rules matrix checks passed"
