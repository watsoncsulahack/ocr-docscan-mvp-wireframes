#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

KEY="${1:-${GEMINI_API_KEY:-}}"
if [[ -z "$KEY" ]]; then
  read -r -s -p "Enter GEMINI_API_KEY: " KEY
  echo
fi

if [[ -z "$KEY" ]]; then
  echo "No key provided." >&2
  exit 1
fi

python3 - "$ENV_FILE" "$KEY" <<'PY'
import pathlib, sys

env_path = pathlib.Path(sys.argv[1])
key = sys.argv[2].strip()

lines = []
if env_path.exists():
    lines = env_path.read_text(encoding='utf-8').splitlines()

updates = {
    'GEMINI_API_KEY': key,
    'LLM_PROVIDER': 'gemini',
    'OCR_PROVIDER': 'ocrspace',
    'ENABLE_LLM_POSTPROCESS': '1',
}

seen = set()
out = []
for ln in lines:
    s = ln.strip()
    if not s or s.startswith('#') or '=' not in ln:
        out.append(ln)
        continue
    k, _ = ln.split('=', 1)
    k = k.strip()
    if k in updates:
        out.append(f"{k}={updates[k]}")
        seen.add(k)
    else:
        out.append(ln)

for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")

env_path.write_text("\n".join(out).rstrip() + "\n", encoding='utf-8')
print(env_path)
PY

chmod 600 "$ENV_FILE"
echo "Saved Gemini config to $ENV_FILE"
echo "Now run: bash $ROOT_DIR/scripts/start_backend_local.sh"
