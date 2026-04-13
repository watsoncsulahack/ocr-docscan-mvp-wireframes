# OCR Doc Scan MVP (Frontend + Demo Backend)

This repo now includes:

- Static GitHub Pages frontend (`index.html`, `upload.html`, `review.html`, etc.)
- Minimal FastAPI backend for demo state (`backend/main.py`)

## Current Demo Scope

- Camera/image upload from phone browser
- `/scan` endpoint (currently placeholder extraction from filename; OCR phase next)
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

## Deploy backend (Render recommended)

This repo includes `render.yaml`. Create a Render web service from this repo:
- Build: `pip install -r backend/requirements.txt`
- Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

Then set `window.OCR_BACKEND_URL` in `config.js` to your Render URL and push.

## Security Notes (demo-light)

- CORS limited to GitHub Pages + localhost defaults
- File type and size validation in `/scan`
- Reset route uses confirmation token (`RESET_DEMO`)
