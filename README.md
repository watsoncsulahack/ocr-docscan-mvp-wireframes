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
uvicorn backend.main:app --reload --port 8010
```

### 2) Frontend

```bash
python3 -m http.server 8080
```

Open:
- Frontend: `http://127.0.0.1:8080`
- Backend health: `http://127.0.0.1:8010/health`

## GitHub Pages + Backend Wiring

- Frontend reads backend URL from `config.js` (`window.OCR_BACKEND_URL`)
- You can override at runtime from the index page and save in localStorage.

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

`index.html` now includes:
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

### Optional local OCR extras

- `OCR_MVP_INSTALL_LOCAL_OCR=1` installs `backend/requirements-optional-local-ocr.txt`
- `OCR_MVP_INSTALL_DOCTR=1` installs `backend/requirements-optional-doctr.txt`
- `ENABLE_DOCTR=1` enables DocTR usage at runtime

## Security Notes (demo-light)

- CORS limited to GitHub Pages + localhost defaults
- File type and size validation in `/scan`
- Reset route uses confirmation token (`RESET_DEMO`)
- In no-account tunnel mode, backend data stays on your local machine (SQLite local), traffic is relayed through tunnel provider.
