#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

sid="$(read_submission_id)"
echo "GET $BASE_URL/admin/audit?submissionId=$sid"
curl -sS "$BASE_URL/admin/audit?submissionId=$sid" | pretty
