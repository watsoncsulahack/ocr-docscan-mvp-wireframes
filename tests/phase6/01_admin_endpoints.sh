#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "[phase6] admin endpoint checks on $BASE_URL"

subs="$(curl -sS "$BASE_URL/admin/submissions")"
flagged="$(curl -sS "$BASE_URL/admin/flagged")"
audit="$(curl -sS "$BASE_URL/admin/audit?limit=20")"

python3 - <<'PY' "$subs" "$flagged" "$audit"
import json,sys
subs=json.loads(sys.argv[1])
flag=json.loads(sys.argv[2])
aud=json.loads(sys.argv[3])

assert subs.get("ok") is True
assert isinstance(subs.get("submissions"), list)
assert flag.get("ok") is True
assert isinstance(flag.get("submissions"), list)
for s in flag.get("submissions", []):
    assert s.get("status") in ("NEEDS_REVIEW","DUPLICATE"), s
assert aud.get("ok") is True
assert isinstance(aud.get("audit"), list)
print("PASS")
PY

echo "[phase6] admin endpoint checks passed"
