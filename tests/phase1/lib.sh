#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
STATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.state"
mkdir -p "$STATE_DIR"

save_submission_id() {
  local json="$1"
  python - "$json" "$STATE_DIR/submission_id" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
sid=obj.get("submissionId")
if not sid:
    raise SystemExit("No submissionId in response")
open(sys.argv[2],"w").write(sid)
print(sid)
PY
}

read_submission_id() {
  if [[ ! -f "$STATE_DIR/submission_id" ]]; then
    echo "Missing $STATE_DIR/submission_id. Run 01_submit_endpoint.sh first." >&2
    exit 1
  fi
  cat "$STATE_DIR/submission_id"
}

pretty() {
  python -m json.tool
}
