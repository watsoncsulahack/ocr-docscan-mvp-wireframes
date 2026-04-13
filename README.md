# OCR Doc Scan MVP (Frontend + Demo Backend)

This repo now includes:

- Static GitHub Pages frontend (`index.html`, `upload.html`, `review.html`, etc.)
- Minimal FastAPI backend for demo state (`backend/main.py`)

## Current Demo Scope

- Camera/image upload from phone browser
- PDF upload support with digital-text parsing fallback
- `/scan` endpoint with hybrid extraction pipeline:
  - PDF digital parsers: `pdfplumber` / `PyMuPDF`
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
# OCR binary required for full image OCR:
# Ubuntu/Debian: sudo apt-get install -y tesseract-ocr
# Optional alternative OCR engine:
# pip install -r backend/requirements-optional-doctr.txt
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

Stop tunnel + backend:

```bash
bash ./scripts/stop_share_demo.sh
```

## Render deployment (optional)

This repo includes `render.yaml`. If you want a persistent hosted backend later:
- Build: `pip install -r backend/requirements.txt`
- Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

## Runtime flags

- `ENABLE_LLM_POSTPROCESS=1` (default) : enable LLM JSON extraction post-process
- `LLM_BASE_URL=http://127.0.0.1:18084` : OpenAI-compatible local endpoint
- `LLM_MODEL=<optional>` : override model id
- `LLM_INCLUDE_IMAGE=1` : include image payload in LLM request when possible
- `ENABLE_DOCTR=1` : enable DocTR OCR path if installed

## Security Notes (demo-light)

- CORS limited to GitHub Pages + localhost defaults
- File type and size validation in `/scan`
- Reset route uses confirmation token (`RESET_DEMO`)
- In no-account tunnel mode, backend data stays on your local machine (SQLite local), traffic is relayed through tunnel provider.
