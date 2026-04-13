import datetime as dt
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "records.sqlite"

APP_ORIGINS = [
    "https://watsoncsulahack.github.io",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
]

MAX_FILE_BYTES = 8 * 1024 * 1024
CONTAINER_RE = re.compile(r"\b([A-Z]{4}[0-9]{7})\b")
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          containerNo TEXT NOT NULL,
          date TEXT NOT NULL,
          sourceFileName TEXT,
          corrected INTEGER NOT NULL DEFAULT 0,
          createdAt TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_records_createdAt ON records(createdAt DESC);
        CREATE INDEX IF NOT EXISTS idx_records_containerNo ON records(containerNo);
        """
    )
    conn.commit()
    conn.close()


def valid_container(value: str) -> bool:
    return bool(CONTAINER_RE.fullmatch((value or "").strip()))


def valid_date(value: str) -> bool:
    try:
        dt.datetime.strptime((value or "").strip(), "%m/%d/%Y")
        return True
    except Exception:
        return False


class RecordIn(BaseModel):
    containerNo: str = Field(min_length=11, max_length=11)
    date: str
    sourceFileName: Optional[str] = None
    corrected: bool = False


app = FastAPI(title="OCR DocScan MVP Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"ok": True, "service": "ocr-docscan-mvp-backend", "time": now_iso()}


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    ctype = (file.content_type or "").lower()
    if not ctype.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed in this demo.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large.")

    safe_name = Path(file.filename or "capture.jpg").name
    temp_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    temp_path = UPLOAD_DIR / temp_name
    temp_path.write_bytes(raw)

    # OCR placeholder: for demo deployment readiness, parsing from filename first.
    # Replace with pytesseract pipeline in next phase.
    probe_text = f"{safe_name}"
    containers = list(dict.fromkeys(CONTAINER_RE.findall(probe_text.upper())))
    dates = list(dict.fromkeys(DATE_RE.findall(probe_text)))

    issues = []
    if not containers:
        issues.append("no_container_found")
    elif len(containers) > 1:
        issues.append("multiple_container_matches")

    if not dates:
        issues.append("invalid_or_missing_date")
    elif len(dates) > 1:
        issues.append("multiple_date_matches")

    extracted = {
        "containerNo": containers[0] if containers else "",
        "date": dates[0] if dates else dt.datetime.now().strftime("%m/%d/%Y"),
    }

    return {
        "ok": True,
        "scanId": str(uuid.uuid4()),
        "extracted": extracted,
        "candidates": {"containerNos": containers, "dates": dates},
        "issues": issues,
        "requiresReview": True,
        "sourceFileName": safe_name,
        "ocrMode": "placeholder_filename_parser",
    }


@app.post("/records")
def add_record(payload: RecordIn):
    container = (payload.containerNo or "").strip().upper()
    date = (payload.date or "").strip()
    if not valid_container(container):
        raise HTTPException(status_code=400, detail="Invalid containerNo format.")
    if not valid_date(date):
        raise HTTPException(status_code=400, detail="Date must be MM/DD/YYYY.")

    created = now_iso()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO records(containerNo, date, sourceFileName, corrected, createdAt) VALUES (?, ?, ?, ?, ?)",
        (container, date, payload.sourceFileName, 1 if payload.corrected else 0, created),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "record": {
            "id": rid,
            "containerNo": container,
            "date": date,
            "sourceFileName": payload.sourceFileName,
            "corrected": payload.corrected,
            "createdAt": created,
        },
    }


@app.get("/records")
def get_records():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, containerNo, date, sourceFileName, corrected, createdAt FROM records ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["corrected"] = bool(r.get("corrected"))
    return {"ok": True, "records": rows}


class ResetIn(BaseModel):
    confirm: str


@app.post("/reset-demo")
def reset_demo(payload: ResetIn):
    if payload.confirm != "RESET_DEMO":
        raise HTTPException(status_code=400, detail="Invalid reset confirmation token")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM records")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deletedCount": deleted}
