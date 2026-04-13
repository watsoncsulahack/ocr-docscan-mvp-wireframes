import base64
import datetime as dt
import io
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional, Tuple
from urllib import error as url_error
from urllib import request as url_request

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from PIL import Image, ImageEnhance, ImageOps
except Exception:  # pragma: no cover
    Image = None

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor
except Exception:  # pragma: no cover
    DocumentFile = None
    ocr_predictor = None

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

OWNER_ALIAS = {
    "SKUU": "SKYU",
    "SKU": "SKYU",
    "SKY": "SKYU",
}

DOCTR_MODEL = None
LLM_MODEL_CACHE = None


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
    text = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    if len(text) >= 4:
        prefix = text[:4]
        if prefix in OWNER_ALIAS:
            text = OWNER_ALIAS[prefix] + text[4:]
    if len(text) >= 3:
        # handle 3-letter owner code where category is dropped (common OCR issue)
        if re.fullmatch(r"[A-Z]{3}[0-9]{7}", text):
            text = OWNER_ALIAS.get(text[:3], text[:3] + "U") + text[3:]
    return text


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
    table = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
    return token.translate(table)


def _ocr_digits(token: str) -> str:
    table = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8"})
    return token.translate(table)


def extract_container_candidates(raw_text: str) -> List[str]:
    text = re.sub(r"[^A-Z0-9\s]", " ", (raw_text or "").upper())
    candidates: List[str] = []

    # contiguous hit
    candidates.extend(CONTAINER_RE.findall(text))

    # spaced variants: SKYU 400093 2 or SKYU 4000932
    for m in re.finditer(r"\b([A-Z0-9]{3,4})\s*([0-9A-Z]{6})\s*([0-9A-Z])\b", text):
        p1 = _ocr_letters(m.group(1))
        p2 = _ocr_digits(m.group(2))
        p3 = _ocr_digits(m.group(3))
        candidates.append(f"{p1}{p2}{p3}")

    for m in re.finditer(r"\b([A-Z0-9]{3,4})\s*([0-9A-Z]{7})\b", text):
        p1 = _ocr_letters(m.group(1))
        p2 = _ocr_digits(m.group(2))
        candidates.append(f"{p1}{p2}")

    tokens = re.findall(r"[A-Z0-9]+", text)
    for i in range(len(tokens) - 1):
        t1 = _ocr_letters(tokens[i])
        t2 = _ocr_digits(tokens[i + 1])
        if re.fullmatch(r"[A-Z]{3,4}", t1) and re.fullmatch(r"[0-9]{7}", t2):
            candidates.append(t1 + t2)
    for i in range(len(tokens) - 2):
        t1 = _ocr_letters(tokens[i])
        t2 = _ocr_digits(tokens[i + 1])
        t3 = _ocr_digits(tokens[i + 2])
        if re.fullmatch(r"[A-Z]{3,4}", t1) and re.fullmatch(r"[0-9]{6}", t2) and re.fullmatch(r"[0-9]", t3):
            candidates.append(t1 + t2 + t3)

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


def extract_pdf_text_and_image(raw: bytes) -> Tuple[str, Optional[object], List[str]]:
    notes: List[str] = []
    text_parts: List[str] = []
    first_page_image = None

    if pdfplumber is not None:
        try:
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages[:3]:
                    t = page.extract_text() or ""
                    if t.strip():
                        text_parts.append(t)
            notes.append("pdfplumber_text")
        except Exception:
            notes.append("pdfplumber_failed")

    if fitz is not None:
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
            for i in range(min(3, len(doc))):
                t = doc.load_page(i).get_text("text") or ""
                if t.strip():
                    text_parts.append(t)
            notes.append("pymupdf_text")

            if len(doc) > 0 and Image is not None:
                pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(2, 2))
                first_page_image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                notes.append("pymupdf_rasterized_page0")
        except Exception:
            notes.append("pymupdf_failed")

    joined = "\n".join([p for p in text_parts if p.strip()]).strip()
    return joined, first_page_image, notes


def candidate_regions(image):
    if image is None:
        return []

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

    uniq = []
    seen = set()
    for t in texts:
        key = re.sub(r"\s+", " ", t).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(key)

    return uniq, True, None


def run_doctr(image_path: Path) -> Tuple[List[str], bool, Optional[str]]:
    global DOCTR_MODEL
    if DocumentFile is None or ocr_predictor is None:
        return [], False, "doctr_dependency_missing"

    if os.getenv("ENABLE_DOCTR", "0") != "1":
        return [], False, "doctr_disabled"

    try:
        if DOCTR_MODEL is None:
            DOCTR_MODEL = ocr_predictor(pretrained=True)
        doc = DocumentFile.from_images(str(image_path))
        result = DOCTR_MODEL(doc)
        txt = (result.render() or "").strip()
        return ([txt] if txt else []), True, None
    except Exception as err:
        return [], False, f"doctr_error:{err}"


def extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def resolve_llm_model(base_url: str) -> Optional[str]:
    global LLM_MODEL_CACHE
    if LLM_MODEL_CACHE:
        return LLM_MODEL_CACHE
    try:
        req = url_request.Request(f"{base_url}/v1/models", headers={"Content-Type": "application/json"})
        with url_request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8", "ignore"))
        models = data.get("data") or []
        if models:
            LLM_MODEL_CACHE = models[0].get("id")
    except Exception:
        return None
    return LLM_MODEL_CACHE


def llm_postprocess(raw_text: str, containers: List[str], dates: List[str], image_bytes: Optional[bytes]) -> Tuple[Optional[dict], Optional[str]]:
    if os.getenv("ENABLE_LLM_POSTPROCESS", "1") != "1":
        return None, "llm_disabled"

    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:18084").rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip() or resolve_llm_model(base_url)
    if not model:
        return None, "llm_model_unavailable"

    prompt = (
        "Extract containerNo and date (MM/DD/YYYY) from OCR text. "
        "Container should follow ISO 6346 (AAAA1234567). "
        "Return strict JSON with keys: containerNo, date."
        f"\n\nOCR TEXT:\n{raw_text[:2000]}"
        f"\n\nCANDIDATE CONTAINERS: {containers}"
        f"\nCANDIDATE DATES: {dates}"
    )

    content = [{"type": "text", "text": prompt}]
    if image_bytes and os.getenv("LLM_INCLUDE_IMAGE", "1") == "1":
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You extract logistics fields and return valid JSON only."},
            {"role": "user", "content": content},
        ],
    }

    req = url_request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=25) as res:
            body = json.loads(res.read().decode("utf-8", "ignore"))
        text = (
            (((body.get("choices") or [{}])[0].get("message") or {}).get("content"))
            if isinstance(body, dict)
            else ""
        )
        parsed = extract_json_object(text if isinstance(text, str) else "")
        if not parsed:
            return None, "llm_json_parse_failed"

        out = {
            "containerNo": normalize_container(str(parsed.get("containerNo", ""))),
            "date": str(parsed.get("date", "")).strip(),
        }
        if out["containerNo"] and not valid_container(out["containerNo"]):
            out["containerNo"] = ""
        if out["date"] and not valid_date(out["date"]):
            out["date"] = ""
        return out, None
    except url_error.HTTPError as err:
        return None, f"llm_http_{err.code}"
    except Exception as err:
        return None, f"llm_error:{err}"


class RecordIn(BaseModel):
    containerNo: str = Field(min_length=1, max_length=32)
    date: str
    sourceFileName: Optional[str] = None
    corrected: bool = False


app = FastAPI(title="OCR DocScan MVP Backend", version="0.3.0")
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
        "pdfParserAvailable": bool(pdfplumber is not None or fitz is not None),
        "doctrAvailable": bool(DocumentFile is not None and ocr_predictor is not None),
    }


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    ctype = (file.content_type or "").lower()
    filename = Path(file.filename or "capture").name
    is_pdf = ctype == "application/pdf" or filename.lower().endswith(".pdf")
    is_image = ctype.startswith("image/") or filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp"))

    if not (is_pdf or is_image):
        raise HTTPException(status_code=400, detail="Only image or PDF uploads are allowed.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large.")

    temp_name = f"{uuid.uuid4().hex[:12]}_{filename}"
    temp_path = UPLOAD_DIR / temp_name
    temp_path.write_bytes(raw)

    pipeline_notes: List[str] = []
    raw_text_parts: List[str] = []
    image_for_ocr = None

    if is_pdf:
        txt, first_img, notes = extract_pdf_text_and_image(raw)
        raw_text_parts.append(txt)
        pipeline_notes.extend(notes)
        image_for_ocr = first_img
        pipeline_notes.append("input_pdf")
    else:
        if Image is not None:
            try:
                image_for_ocr = Image.open(io.BytesIO(raw)).convert("RGB")
            except Exception:
                image_for_ocr = None
        pipeline_notes.append("input_image")

    tesseract_texts, tess_ok, tess_err = run_tesseract(image_for_ocr)
    if tess_ok:
        pipeline_notes.append("ocr_tesseract")
        raw_text_parts.extend(tesseract_texts)
    elif tess_err:
        pipeline_notes.append(tess_err)

    doctr_texts, doctr_ok, doctr_err = run_doctr(temp_path)
    if doctr_ok and doctr_texts:
        pipeline_notes.append("ocr_doctr")
        raw_text_parts.extend(doctr_texts)
    elif doctr_err and doctr_err not in ("doctr_disabled", "doctr_dependency_missing"):
        pipeline_notes.append(doctr_err)

    raw_text_parts.append(filename)
    raw_text = "\n".join([p for p in raw_text_parts if p]).strip()

    containers = extract_container_candidates(raw_text)
    dates = extract_date_candidates(raw_text)

    llm_structured, llm_error = llm_postprocess(raw_text, containers, dates, raw if is_image else None)
    if llm_structured:
        pipeline_notes.append("llm_postprocess")
    elif llm_error:
        pipeline_notes.append(llm_error)

    extracted_container = (llm_structured or {}).get("containerNo") or (containers[0] if containers else "")
    extracted_date = (llm_structured or {}).get("date") or (dates[0] if dates else dt.datetime.now().strftime("%m/%d/%Y"))

    issues = []
    if not containers and not extracted_container:
        issues.append("no_container_found")
    elif len(containers) > 1:
        issues.append("multiple_container_matches")

    if not dates and not valid_date(extracted_date):
        issues.append("invalid_or_missing_date")
    elif len(dates) > 1:
        issues.append("multiple_date_matches")

    if not tess_ok and not doctr_ok and not (is_pdf and raw_text):
        issues.append("ocr_engine_unavailable")

    candidate_details = [{"value": c, "iso6346Valid": iso6346_is_valid(c)} for c in containers]

    return {
        "ok": True,
        "scanId": str(uuid.uuid4()),
        "extracted": {"containerNo": extracted_container, "date": extracted_date},
        "candidates": {"containerNos": containers, "dates": dates},
        "candidateDetails": {"containerNos": candidate_details},
        "issues": issues,
        "requiresReview": True,
        "sourceFileName": filename,
        "ocrMode": "hybrid_pipeline",
        "rawTextPreview": raw_text[:1200],
        "pipeline": pipeline_notes,
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
