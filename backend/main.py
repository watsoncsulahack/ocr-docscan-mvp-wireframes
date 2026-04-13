import datetime as dt
import io
import re
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
except Exception:  # pragma: no cover - runtime dependency check
    Image = None

try:
    import pytesseract
except Exception:  # pragma: no cover - runtime dependency check
    pytesseract = None

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
DATE_RE = re.compile(r"\b((?:0[1-9]|1[0-2])/(?:0[1-9]|[12][0-9]|3[01])/[0-9]{4})\b")

ISO6346_LETTER_VALUES = {
    "A": 10,
    "B": 12,
    "C": 13,
    "D": 14,
    "E": 15,
    "F": 16,
    "G": 17,
    "H": 18,
    "I": 19,
    "J": 20,
    "K": 21,
    "L": 23,
    "M": 24,
    "N": 25,
    "O": 26,
    "P": 27,
    "Q": 28,
    "R": 29,
    "S": 30,
    "T": 31,
    "U": 32,
    "V": 34,
    "W": 35,
    "X": 36,
    "Y": 37,
    "Z": 38,
}


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


def normalize_container(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def valid_container(value: str) -> bool:
    return bool(CONTAINER_RE.fullmatch(normalize_container(value)))


def valid_date(value: str) -> bool:
    try:
        dt.datetime.strptime((value or "").strip(), "%m/%d/%Y")
        return True
    except Exception:
        return False


def iso6346_check_digit(prefix10: str) -> Optional[int]:
    if len(prefix10) != 10:
        return None
    total = 0
    for idx, ch in enumerate(prefix10):
        if ch.isdigit():
            value = int(ch)
        else:
            value = ISO6346_LETTER_VALUES.get(ch)
            if value is None:
                return None
        total += value * (2**idx)
    cd = total % 11
    return 0 if cd == 10 else cd


def iso6346_is_valid(container: str) -> bool:
    value = normalize_container(container)
    if not CONTAINER_RE.fullmatch(value):
        return False
    expected = iso6346_check_digit(value[:10])
    if expected is None:
        return False
    return expected == int(value[-1])


def _ocr_letters(token: str) -> str:
    # convert common OCR digit confusions in owner/equipment letters
    table = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
    return token.translate(table)


def _ocr_digits(token: str) -> str:
    # convert common OCR letter confusions in numeric sections
    table = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8"})
    return token.translate(table)


def extract_container_candidates(raw_text: str) -> List[str]:
    text = re.sub(r"[^A-Z0-9\s]", " ", (raw_text or "").upper())
    candidates: List[str] = []

    # contiguous hit
    candidates.extend(CONTAINER_RE.findall(text))

    # spaced variants: SKYU 400093 2 or SKYU 4000932
    for m in re.finditer(r"\b([A-Z0-9]{4})\s*([0-9A-Z]{6})\s*([0-9A-Z])\b", text):
        p1 = _ocr_letters(m.group(1))
        p2 = _ocr_digits(m.group(2))
        p3 = _ocr_digits(m.group(3))
        candidates.append(f"{p1}{p2}{p3}")

    for m in re.finditer(r"\b([A-Z0-9]{4})\s*([0-9A-Z]{7})\b", text):
        p1 = _ocr_letters(m.group(1))
        p2 = _ocr_digits(m.group(2))
        candidates.append(f"{p1}{p2}")

    # token window fallback
    tokens = re.findall(r"[A-Z0-9]+", text)
    for i in range(len(tokens) - 1):
        t1 = _ocr_letters(tokens[i])
        t2 = _ocr_digits(tokens[i + 1])
        if re.fullmatch(r"[A-Z]{4}", t1) and re.fullmatch(r"[0-9]{7}", t2):
            candidates.append(t1 + t2)
    for i in range(len(tokens) - 2):
        t1 = _ocr_letters(tokens[i])
        t2 = _ocr_digits(tokens[i + 1])
        t3 = _ocr_digits(tokens[i + 2])
        if re.fullmatch(r"[A-Z]{4}", t1) and re.fullmatch(r"[0-9]{6}", t2) and re.fullmatch(r"[0-9]", t3):
            candidates.append(t1 + t2 + t3)

    # dedupe + rank (ISO valid first)
    seen = set()
    uniq: List[str] = []
    for c in candidates:
        n = normalize_container(c)
        if not CONTAINER_RE.fullmatch(n):
            continue
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)

    uniq.sort(key=lambda c: (0 if iso6346_is_valid(c) else 1, c))
    return uniq


def extract_date_candidates(raw_text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for d in DATE_RE.findall(raw_text or ""):
        if d not in seen and valid_date(d):
            out.append(d)
            seen.add(d)
    return out


def candidate_regions(image):
    if image is None:
        return []

    # keep OCR cost bounded for mobile/demo workloads
    max_w = 1600
    if image.width > max_w:
        ratio = max_w / float(image.width)
        image = image.resize((max_w, int(image.height * ratio)))

    w, h = image.size
    box_specs = [
        ((0, 0, w, h), [1.0]),
        ((0, 0, int(w * 0.60), int(h * 0.45)), [1.0, 2.0]),
        ((0, int(h * 0.05), int(w * 0.55), int(h * 0.70)), [1.0, 2.0]),
        ((int(w * 0.20), int(h * 0.06), int(w * 0.56), int(h * 0.34)), [3.0, 4.0]),
        ((int(w * 0.24), int(h * 0.04), int(w * 0.58), int(h * 0.38)), [3.0, 4.0]),
    ]

    out = []
    for box, scales in box_specs:
        c = image.crop(box)
        for scale in scales:
            if scale == 1.0:
                out.append(c)
            else:
                out.append(c.resize((max(20, int(c.width * scale)), max(20, int(c.height * scale)))))
    return out


def preprocess_variants(image):
    if image is None:
        return []
    gray = ImageOps.grayscale(image)
    auto = ImageOps.autocontrast(gray)
    hi_contrast = ImageEnhance.Contrast(auto).enhance(2.2)
    threshold = hi_contrast.point(lambda p: 255 if p > 150 else 0)
    return [hi_contrast, threshold]


def run_tesseract(image) -> Tuple[List[str], bool, Optional[str]]:
    if pytesseract is None or Image is None or image is None:
        return [], False, "ocr_dependency_missing"

    texts: List[str] = []
    cfgs = [
        "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/- ",
        "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/- ",
    ]

    try:
        for region in candidate_regions(image):
            for variant in preprocess_variants(region):
                for cfg in cfgs:
                    txt = pytesseract.image_to_string(variant, config=cfg)
                    txt = (txt or "").strip()
                    if txt:
                        texts.append(txt)
    except Exception as err:
        msg = str(err).lower()
        if "tesseract" in msg and ("not found" in msg or "isn't installed" in msg):
            return [], False, "tesseract_binary_missing"
        return [], False, f"ocr_error:{err}"

    # dedupe
    uniq = []
    seen = set()
    for t in texts:
        key = re.sub(r"\s+", " ", t).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(key)

    return uniq, True, None


class RecordIn(BaseModel):
    containerNo: str = Field(min_length=11, max_length=32)
    date: str
    sourceFileName: Optional[str] = None
    corrected: bool = False


app = FastAPI(title="OCR DocScan MVP Backend", version="0.2.0")
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
    return {
        "ok": True,
        "service": "ocr-docscan-mvp-backend",
        "time": now_iso(),
        "ocrLibrariesAvailable": bool(Image is not None and pytesseract is not None),
    }


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

    image = None
    if Image is not None:
        try:
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            image = None

    ocr_texts, ocr_ok, ocr_error = run_tesseract(image)

    # fallback keeps demo usable if OCR binary is unavailable
    probe_text_parts = []
    probe_text_parts.extend(ocr_texts)
    probe_text_parts.append(safe_name)
    probe_text = "\n".join(probe_text_parts)

    containers = extract_container_candidates(probe_text)
    dates = extract_date_candidates(probe_text)

    issues = []
    if not containers:
        issues.append("no_container_found")
    elif len(containers) > 1:
        issues.append("multiple_container_matches")

    if not dates:
        issues.append("invalid_or_missing_date")
    elif len(dates) > 1:
        issues.append("multiple_date_matches")

    if not ocr_ok:
        issues.append("ocr_engine_unavailable")

    extracted = {
        "containerNo": containers[0] if containers else "",
        "date": dates[0] if dates else dt.datetime.now().strftime("%m/%d/%Y"),
    }

    container_details = [{"value": c, "iso6346Valid": iso6346_is_valid(c)} for c in containers]

    return {
        "ok": True,
        "scanId": str(uuid.uuid4()),
        "extracted": extracted,
        "candidates": {"containerNos": containers, "dates": dates},
        "candidateDetails": {"containerNos": container_details},
        "issues": issues,
        "requiresReview": True,
        "sourceFileName": safe_name,
        "ocrMode": "tesseract_image" if ocr_ok else "fallback_filename_only",
        "ocrError": ocr_error,
        "rawTextPreview": "\n".join(ocr_texts)[:600],
    }


@app.post("/records")
def add_record(payload: RecordIn):
    container = normalize_container(payload.containerNo or "")
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
