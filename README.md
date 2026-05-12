# OCR Doc Scan MVP (Frontend + Demo Backend)

This repo now includes:

- Static GitHub Pages frontend (`index.html`, `upload.html`, `review.html`, etc.)
- Minimal FastAPI backend for demo state (`backend/main.py`)

## Current Demo Scope

- Camera/image upload from phone browser
- PDF upload support with digital-text parsing fallback
- `/scan` endpoint with hybrid extraction pipeline:
  - PDF digital parsers: `pypdf` / `pdfplumber` / `PyMuPDF`
  - OCR engine: `Tesseract`
  - optional OCR engine: `DocTR` (feature-flagged)
  - LLM post-processing block for final structured extraction
- ISO 6346-aware container normalization, correction, and ranking
- Review/correct fields
- Save to SQLite (`containerNo`, `date`, `sourceFileName`, `corrected`, `createdAt`)
- Records table reflects backend data

## Repo Structure

- Frontend pages: root HTML/CSS/JS
- Backend app: `backend/`
- Runtime data: `data/records.sqlite`
- Uploaded files: `uploads/`
- Render deploy config: `render.yaml`

## Run locally

### Universal bootstrap (single entrypoint)

Use one script on Android/Termux or regular Linux/macOS devices:

```bash
bash ./scripts/bootstrap_mvp.sh
```

Optional env knobs:

```bash
OCR_MVP_PROFILE=phone OCR_MVP_LLM=gemini bash ./scripts/bootstrap_mvp.sh
OCR_MVP_BACKEND_PORT=8010 OCR_MVP_FRONTEND_PORT=8080 bash ./scripts/bootstrap_mvp.sh
./scripts/bootstrap_mvp.sh --model glm-ocr
bash ./scripts/bootstrap_mvp.sh --clean
```

What it does:
- installs/verifies base dependencies
- clones/updates repo when run outside repo
- initializes/updates git submodules (including `third_party/ollama`)
- creates/uses `.venv` and installs `backend/requirements.txt`
- starts local Ollama (managed), pulls model, then runs warm prompt via `scripts/ollama_local.sh`
- launches backend + frontend (tmux sessions when available)
- prints MVP + admin URLs

Termux note:
- On Termux, bootstrap installs Rust/clang/pkg-config and uses the same
  dependency set as other platforms, so `pydantic-core` can compile when
  wheels are unavailable.

### Vanilla Android (Termux + tmux) one-shot bootstrap

On a fresh Android test device (Termux):

```bash
bash ./scripts/bootstrap_android_tmux.sh
```

This is a compatibility wrapper around `bootstrap_mvp.sh` with Android-friendly defaults.

This script will:
- install required Termux packages (`git`, `python`, `tmux`, `curl`)
- clone or update the repo
- create `.venv` + install Python deps
- start backend in tmux session `ocr-backend`
- start frontend in tmux session `ocr-frontend`
- print working URLs and health status

Useful tmux commands:

```bash
tmux attach -t ocr-backend
tmux attach -t ocr-frontend
tmux ls
```

### 1) Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
# Optional local OCR stack (heavier; not required for cloud OCR mode):
# pip install -r backend/requirements-optional-local-ocr.txt
# Optional alternative OCR engine:
# pip install -r backend/requirements-optional-doctr.txt
# OCR binary required only for local Tesseract mode:
# Ubuntu/Debian: sudo apt-get install -y tesseract-ocr
uvicorn backend.main:app --reload --port 8000
```

### 2) Frontend

```bash
python3 -m http.server 8080
```

Open:
- Frontend: `http://127.0.0.1:8080`
- Backend health: `http://127.0.0.1:8000/health`

### Admin panel (separate launcher)

Run the admin panel on its own local port (defaults to `8091`) with `admin.html` as the default route:

```bash
bash ./scripts/start_admin_panel.sh
```

Open:
- `http://127.0.0.1:8091/`

Optional custom port:

```bash
ADMIN_PANEL_PORT=8119 bash ./scripts/start_admin_panel.sh
```

### Admin panel on GitHub Pages (with fake DB)

`admin.html` now supports a built-in mock database fallback for static hosting.

- On `github.io`, if local backend is unreachable, it auto-switches to mock DB.
- You can force mock mode anywhere with `?mockdb=1`.

Example:

```text
https://<your-user>.github.io/ocr-docscan-mvp-wireframes/admin.html?mockdb=1
```

This keeps the UI looking and behaving like a real review queue (open/review/approve/reject) while persisting fake state in browser `localStorage`.

## GitHub Pages + Backend Wiring

- Frontend reads backend URL from `config.js` (`window.OCR_BACKEND_URL`)
- You can override at runtime from the index page and save in localStorage.
- GitHub Pages deployment workflow: `.github/workflows/deploy-pages.yml` (push to `main` or `sprint3/phase0-baseline-local-first`)

## One project, multi-platform (phone + laptop)

Use one wrapper script for both devices:

```bash
# Local backend only
bash ./scripts/run_dev.sh up

# Local backend + public tunnel
bash ./scripts/run_dev.sh share

# Stop tunnel + backend
bash ./scripts/run_dev.sh down
```

Optional profile and LLM mode knobs:

```bash
OCR_MVP_PROFILE=phone  bash ./scripts/run_dev.sh up
OCR_MVP_PROFILE=laptop bash ./scripts/run_dev.sh up
OCR_MVP_LLM=ollama     bash ./scripts/run_dev.sh up
OCR_MVP_LOCAL_OCR=1    bash ./scripts/run_dev.sh up
bash ./scripts/run_dev.sh up --clean
```

Notes:
- `OCR_MVP_PROFILE=auto` (default) auto-detects phone vs laptop.
- `OCR_MVP_LLM=ollama` maps to OpenAI-compatible mode with default `LLM_BASE_URL=http://127.0.0.1:11434/v1`.
- Keep the same repo and scripts on both platforms; only env/profile changes.

### Ollama manager (local)

```bash
bash ./scripts/ollama_local.sh start
bash ./scripts/ollama_local.sh status
bash ./scripts/ollama_local.sh stop
```

Useful env knobs:
- `OCR_MVP_OLLAMA_MODEL` (default `glm-ocr`)
- `OCR_MVP_OLLAMA_AUTO_PULL=1|0`
- `OCR_MVP_OLLAMA_AUTO_RUN=1|0`
- `OCR_MVP_OLLAMA_INSTALL=1` (attempt auto-install via official script if ollama is missing)

Notes:
- On Linux/server installs, Ollama exposes an API + CLI (`ollama list`, `ollama pull`, `ollama run`), not a bundled web GUI.
- The desktop Ollama app provides its own UI on supported desktop platforms.

## No-account sharing mode (free)

If you do not want to create any backend service account, use local backend + temporary tunnel.

```bash
bash ./scripts/share_demo_no_account.sh
```

This prints:
- a public backend URL (temporary)
- a frontend URL already wired with `?backend=...`

It also writes runtime helper files used by the Web Studio control panel:
- `data/runtime/local_backend_url.txt`
- `data/runtime/public_backend_url.txt`
- `data/runtime/public_backend_url.meta`

Notes:
- Script now avoids re-installing Python deps on every run.
- For low-memory Termux devices, keep defaults (cloud OCR/LLM providers) and avoid optional local OCR deps.
- To follow tunnel logs interactively: `OCR_MVP_FOLLOW_LOG=1 bash ./scripts/share_demo_no_account.sh`

Stop tunnel + backend:

```bash
bash ./scripts/stop_share_demo.sh
```

## Render deployment (optional)

This repo includes `render.yaml`. If you want a persistent hosted backend later:
- Build: `pip install -r backend/requirements.txt`
- Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

## Gemini quick wiring

Set key once (stored in `.env`, loaded automatically by `scripts/start_backend_local.sh`):

```bash
bash ./scripts/set_gemini_key.sh
```

Or pass key inline:

```bash
bash ./scripts/set_gemini_key.sh "AIza..."
```

Then run share mode:

```bash
bash ./scripts/share_demo_no_account.sh
```

## Website control panel

Control panel is separated from the GitHub Pages MVP UI:
- MVP UI remains at repo root (`index.html`, `upload.html`, etc.)
- Web Studio control panel lives under `control-panel/`

`control-panel/index.html` includes:
- one-tap local actions (start backend, start/stop share tunnel, refresh generated URL)
- generated backend URL display (read from runtime files)
- Render/tunnel backend -> GitHub Pages URL generator (backend URL only input)
- Gemini one-tap key apply (local backend control API)
- Gemini fallback command generator for Termux

## Runtime flags

### Provider selection

- `OCR_PROVIDER=ocrspace` (recommended for live demos; backend default is `auto`)
  - options: `ocrspace`, `local`, `auto`, `none`
- `LLM_PROVIDER=gemini` (recommended for live demos)
  - options: `gemini`, `openai`, `none`

### OCR.Space

- `OCR_SPACE_API_KEY=<key>` (defaults to `helloworld` if unset, limited)
- `OCR_SPACE_ENGINE=2`
- `OCR_SPACE_LANGUAGE=eng`
- `OCR_TIMEOUT_SEC=25`

### Gemini Flash

- `GEMINI_API_KEY=<key>` (or `GOOGLE_API_KEY`)
- `GEMINI_MODEL=gemini-2.0-flash`
- `LLM_TIMEOUT_SEC=25`
- `LLM_INCLUDE_IMAGE=1`

### Local control API (for Web Studio one-tap actions)

- `ENABLE_LOCAL_CONTROL_API=1` enabled by default in `scripts/start_backend_local.sh`
- endpoint: `POST /control/local/gemini-key` with JSON `{ "apiKey": "..." }`

### Existing/local OpenAI-compatible mode

- `ENABLE_LLM_POSTPROCESS=1` (default)
- `LLM_BASE_URL=http://127.0.0.1:18084`
- `LLM_MODEL=<optional>`
- `LLM_REQUIRE_OCR_AND_IMAGE=1` (default): feed OCR text + image together to LLM for cross-checking
- `DIRECT_IMAGE_TO_LLM=1` only takes effect when `LLM_REQUIRE_OCR_AND_IMAGE=0`

### Optional local OCR extras

- `OCR_MVP_INSTALL_LOCAL_OCR=1` installs `backend/requirements-optional-local-ocr.txt`
- `OCR_MVP_INSTALL_DOCTR=1` installs `backend/requirements-optional-doctr.txt`
- `ENABLE_DOCTR=1` enables DocTR usage at runtime

### Clean database startup

- `./scripts/bootstrap_mvp.sh --clean` or `OCR_MVP_CLEAN_DB=1`
- `./scripts/run_dev.sh up --clean`

This uses a disposable DB file under `data/runtime/records.clean.<timestamp>.sqlite`.
Your primary `data/records.sqlite` is preserved.

## Security Notes (demo-light)

- CORS limited to GitHub Pages + localhost defaults
- File type and size validation in `/scan`
- Reset route uses confirmation token (`RESET_DEMO`)
- In no-account tunnel mode, backend data stays on your local machine (SQLite local), traffic is relayed through tunnel provider.
