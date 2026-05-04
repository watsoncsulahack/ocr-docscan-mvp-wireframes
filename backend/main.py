import base64
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor
except Exception:  # pragma: no cover
    DocumentFile = None
    ocr_predictor = None

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "uploads"
RUNTIME_DIR = DATA_DIR / "runtime"
DB_PATH = DATA_DIR / "records.sqlite"
LOCAL_BACKEND_URL_PATH = RUNTIME_DIR / "local_backend_url.txt"
PUBLIC_BACKEND_URL_PATH = RUNTIME_DIR / "public_backend_url.txt"
PUBLIC_BACKEND_META_PATH = RUNTIME_DIR / "public_backend_url.meta"
TUNNEL_LOG_PATH = Path(os.getenv("OCR_MVP_TUNNEL_LOG", "/tmp/ocr-docscan-tunnel.log"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

APP_ORIGINS = [
    "https://watsoncsulahack.github.io",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8099",
    "http://localhost:8099",
    "http://127.0.0.1:8113",
    "http://localhost:8113",
    "http://127.0.0.1:8118",
    "http://localhost:8118",
]

MAX_FILE_BYTES = 8 * 1024 * 1024
CONTAINER_RE = re.compile(r"\b([A-Z]{4}[0-9]{7})\b")
CONTAINER_STRICT_RE = re.compile(r"^[A-Z]{3}[UJZ][0-9]{7}$")
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


def env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


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

        CREATE TABLE IF NOT EXISTS submissions (
          id TEXT PRIMARY KEY,
          source_file_name TEXT NOT NULL,
          file_type TEXT NOT NULL,
          classifier TEXT NOT NULL,
          status TEXT NOT NULL,
          uploaded_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          file_sha256 TEXT,
          dedupe_key TEXT,
          duplicate_of TEXT,
          fallback_date_used INTEGER NOT NULL DEFAULT 0,
          fallback_date_value TEXT,
          notes TEXT
        );

        CREATE TABLE IF NOT EXISTS document_files (
          id TEXT PRIMARY KEY,
          submission_id TEXT NOT NULL,
          original_filename TEXT,
          source_file_name TEXT NOT NULL,
          file_type TEXT NOT NULL,
          file_sha256 TEXT,
          storage_path TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(submission_id) REFERENCES submissions(id)
        );

        CREATE TABLE IF NOT EXISTS extraction_results (
          id TEXT PRIMARY KEY,
          submission_id TEXT NOT NULL,
          classifier TEXT NOT NULL,
          raw_text TEXT,
          confidence_summary REAL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(submission_id) REFERENCES submissions(id)
        );

        CREATE TABLE IF NOT EXISTS extracted_fields (
          id TEXT PRIMARY KEY,
          submission_id TEXT NOT NULL,
          extraction_result_id TEXT,
          field_name TEXT NOT NULL,
          field_value TEXT,
          confidence REAL,
          is_required INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'extraction',
          created_at TEXT NOT NULL,
          FOREIGN KEY(submission_id) REFERENCES submissions(id),
          FOREIGN KEY(extraction_result_id) REFERENCES extraction_results(id)
        );

        CREATE TABLE IF NOT EXISTS review_tasks (
          id TEXT PRIMARY KEY,
          submission_id TEXT NOT NULL,
          reason_code TEXT NOT NULL,
          status TEXT NOT NULL,
          assigned_to TEXT,
          created_at TEXT NOT NULL,
          resolved_at TEXT,
          resolution_note TEXT,
          FOREIGN KEY(submission_id) REFERENCES submissions(id)
        );

        CREATE TABLE IF NOT EXISTS verified_records (
          id TEXT PRIMARY KEY,
          submission_id TEXT NOT NULL,
          classifier TEXT NOT NULL,
          normalized_payload TEXT NOT NULL,
          approved_by TEXT,
          approved_at TEXT NOT NULL,
          FOREIGN KEY(submission_id) REFERENCES submissions(id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
          id TEXT PRIMARY KEY,
          submission_id TEXT,
          action TEXT NOT NULL,
          actor TEXT NOT NULL,
          details TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(submission_id) REFERENCES submissions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
        CREATE INDEX IF NOT EXISTS idx_submissions_created_at ON submissions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_submissions_file_sha256 ON submissions(file_sha256);
        CREATE INDEX IF NOT EXISTS idx_submissions_dedupe_key ON submissions(dedupe_key);
        CREATE INDEX IF NOT EXISTS idx_document_files_submission_id ON document_files(submission_id);
        CREATE INDEX IF NOT EXISTS idx_extraction_results_submission_id ON extraction_results(submission_id);
        CREATE INDEX IF NOT EXISTS idx_extracted_fields_submission_id ON extracted_fields(submission_id);
        CREATE INDEX IF NOT EXISTS idx_extracted_fields_name ON extracted_fields(field_name);
        CREATE INDEX IF NOT EXISTS idx_review_tasks_submission_id ON review_tasks(submission_id);
        CREATE INDEX IF NOT EXISTS idx_review_tasks_status ON review_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_verified_records_submission_id ON verified_records(submission_id);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_submission_id ON audit_logs(submission_id);
        CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
        """
    )
    conn.commit()
    conn.close()


def upsert_env_values(path: Path, values: dict) -> None:
    lines: List[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    seen = set()
    out: List[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            out.append(line)
            continue
        k, _ = line.split("=", 1)
        key = k.strip()
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)

    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def read_text_if_exists(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return ""


def tail_text_if_exists(path: Path, max_lines: int = 12) -> List[str]:
    text = read_text_if_exists(path)
    if not text:
        return []
    return text.splitlines()[-max_lines:]


def parse_simple_meta(text: str) -> dict:
    out = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def extract_latest_tunnel_url(path: Path, max_lines: int = 300) -> str:
    lines = tail_text_if_exists(path, max_lines=max_lines)
    joined = "\n".join(lines)
    matches = re.findall(r"https://[a-z0-9-]+\.lhr\.life", joined, flags=re.I)
    return matches[-1].strip() if matches else ""


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
    value = normalize_container(value)
    return bool(CONTAINER_STRICT_RE.fullmatch(value)) and iso6346_is_valid(value)


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


def _owner_variants(owner: str) -> List[str]:
    o = normalize_container(owner)
    out = []
    if len(o) != 4:
        return out
    out.append(o)
    last = o[3]
    if last in ("G", "0", "O"):
        out.append(o[:3] + "U")
    if last in ("I", "1", "L"):
        out.append(o[:3] + "J")
    if last in ("2",):
        out.append(o[:3] + "Z")

    uniq = []
    seen = set()
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq


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
        t2 = _ocr_digits(tokens[i + 1])
        if not re.fullmatch(r"[0-9]{7}", t2):
            continue
        for owner in _owner_variants(_ocr_letters(tokens[i])):
            if re.fullmatch(r"[A-Z]{3}[UJZ]", owner):
                candidates.append(owner + t2)

    for i in range(len(tokens) - 2):
        t2 = _ocr_digits(tokens[i + 1])
        t3 = _ocr_digits(tokens[i + 2])
        owners = [o for o in _owner_variants(_ocr_letters(tokens[i])) if re.fullmatch(r"[A-Z]{3}[UJZ]", o)]
        if not owners:
            continue

        # Standard 6+1 serial/check split.
        if re.fullmatch(r"[0-9]{6}", t2) and re.fullmatch(r"[0-9]", t3):
            for owner in owners:
                candidates.append(owner + t2 + t3)

        # OCR drift case: 7 digits then 1 extra digit (e.g. 1208297 + 3 -> 2082973).
        if re.fullmatch(r"[0-9]{7}", t2) and re.fullmatch(r"[0-9]", t3):
            for owner in owners:
                candidates.append(owner + t2)
                candidates.append(owner + t2[1:] + t3)

    # Missing check-digit recovery: SKYU 400093 -> compute SKYU4000932
    for m in re.finditer(r"\b([A-Z0-9]{3,4})\s*([0-9A-Z]{6})\b", text):
        p2 = _ocr_digits(m.group(2))
        for owner4 in _owner_variants(_ocr_letters(m.group(1))):
            prefix = normalize_container(f"{owner4}{p2}")
            if not re.fullmatch(r"[A-Z]{3}[UJZ][0-9]{6}", prefix):
                continue
            cd = iso6346_check_digit(prefix)
            if cd is not None:
                candidates.append(f"{prefix}{cd}")

    # Owner token + nearby serial6 recovery (handles words between owner and serial).
    for i in range(len(tokens)):
        owner = normalize_container(tokens[i])
        if not re.fullmatch(r"[A-Z]{3}[UJZ]", owner):
            continue
        for j in range(i + 1, min(i + 11, len(tokens))):
            s6 = _ocr_digits(tokens[j])
            if not re.fullmatch(r"[0-9]{6}", s6):
                continue
            cd = iso6346_check_digit(owner + s6)
            if cd is not None:
                candidates.append(f"{owner}{s6}{cd}")
            break


    seen = set()
    uniq: List[str] = []
    for c in candidates:
        n = normalize_container(c)
        if not CONTAINER_RE.fullmatch(n):
            continue
        if not valid_container(n):
            continue
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)

    owner_tokens = {
        normalize_container(_ocr_letters(t))
        for t in tokens
        if re.fullmatch(r"[A-Z]{3}[UJZ]", normalize_container(_ocr_letters(t)))
    }

    def _rank(c: str):
        owner = c[:4]
        serial = c[4:10]
        owner_seen = owner in owner_tokens
        serial_seen = any(_ocr_digits(t) == serial for t in tokens)
        return (
            0 if valid_container(c) else 1,
            0 if owner_seen else 1,
            0 if serial_seen else 1,
            c,
        )

    uniq.sort(key=_rank)
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

    if PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(raw))
            for page in reader.pages[:3]:
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(t)
            notes.append("pypdf_text")
        except Exception:
            notes.append("pypdf_failed")

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


def pil_to_jpeg_bytes(image) -> Optional[bytes]:
    if image is None or Image is None:
        return None
    try:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        return None


def ocrspace_image_inputs(image, filename: str) -> List[Tuple[bytes, str, str, str]]:
    """Build a bounded set of OCR.Space image variants for hard container photos."""
    out: List[Tuple[bytes, str, str, str]] = []
    if image is None:
        return out

    base_name = Path(filename or "capture").stem

    def add_variant(tag: str, img_obj) -> None:
        b = pil_to_jpeg_bytes(img_obj)
        if b:
            out.append((b, f"{base_name}_{tag}.jpg", "image/jpeg", tag))

    add_variant("orig", image)

    # full-image preprocess
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    add_variant("prep", gray.convert("RGB"))

    # crops that often contain vertical container markings
    w, h = image.size
    crops = [
        image.crop((0, int(h * 0.05), int(w * 0.60), int(h * 0.95))),
        image.crop((int(w * 0.45), int(h * 0.05), w, int(h * 0.95))),
        image.crop((int(w * 0.15), int(h * 0.10), int(w * 0.85), int(h * 0.90))),
    ]
    for idx, c in enumerate(crops, start=1):
        cgray = ImageOps.autocontrast(c.convert("L"))
        cgray = ImageEnhance.Contrast(cgray).enhance(2.2)
        add_variant(f"region{idx}", cgray.convert("RGB"))

    return out[:6]


def resolve_ocr_provider_chain() -> List[str]:
    provider = os.getenv("OCR_PROVIDER", "auto").strip().lower()
    chain: List[str] = []

    if provider in ("none", "off", "disabled"):
        return chain

    if provider in ("ocrspace", "ocr_space"):
        chain = ["ocrspace"]
        if env_bool("OCR_FALLBACK_LOCAL", "1"):
            chain.append("local")
    elif provider == "auto":
        chain = ["ocrspace", "local"]
    else:
        chain = ["local"]
        if env_bool("OCR_FALLBACK_OCRSPACE", "0"):
            chain.append("ocrspace")

    # de-dup while preserving order
    seen = set()
    out: List[str] = []
    for item in chain:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _encode_multipart(fields: dict, file_field: str, filename: str, file_bytes: bytes, content_type: str) -> Tuple[bytes, str]:
    boundary = f"----OpenClawBoundary{uuid.uuid4().hex}"
    parts: List[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
    )
    parts.append(f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode("utf-8"))
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def run_ocrspace(file_bytes: bytes, filename: str, content_type: str) -> Tuple[List[str], bool, Optional[str]]:
    endpoint = os.getenv("OCR_SPACE_ENDPOINT", "https://api.ocr.space/parse/image").strip()
    api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld").strip() or "helloworld"
    language = os.getenv("OCR_SPACE_LANGUAGE", "eng").strip() or "eng"
    ocr_engine = os.getenv("OCR_SPACE_ENGINE", "2").strip() or "2"

    fields = {
        "apikey": api_key,
        "language": language,
        "OCREngine": ocr_engine,
        "scale": "true",
        "isOverlayRequired": "false",
    }

    body, boundary = _encode_multipart(fields, "file", filename, file_bytes, content_type)
    req = url_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with url_request.urlopen(req, timeout=int(os.getenv("OCR_TIMEOUT_SEC", "25"))) as res:
            payload = json.loads(res.read().decode("utf-8", "ignore"))

        parsed_results = payload.get("ParsedResults") or []
        texts: List[str] = []
        for item in parsed_results:
            txt = str(item.get("ParsedText") or "").strip()
            if txt:
                texts.append(txt)

        if texts:
            return texts, True, None

        errors = payload.get("ErrorMessage") or payload.get("ErrorDetails") or ""
        if isinstance(errors, list):
            errors = "; ".join([str(e) for e in errors if e])
        return [], False, f"ocrspace_no_text:{errors or 'unknown'}"
    except url_error.HTTPError as err:
        return [], False, f"ocrspace_http_{err.code}"
    except Exception as err:
        return [], False, f"ocrspace_error:{err}"


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


def llm_headers(content_type: str = "application/json") -> dict:
    headers = {
        "Content-Type": content_type,
        "Accept": "application/json",
        "User-Agent": os.getenv("LLM_USER_AGENT", "OCR-DocScan-MVP/1.0"),
    }
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Helpful metadata for OpenRouter (optional).
    app_url = os.getenv("OPENROUTER_APP_URL", "").strip()
    app_title = os.getenv("OPENROUTER_APP_TITLE", "").strip()
    if app_url:
        headers["HTTP-Referer"] = app_url
    if app_title:
        headers["X-Title"] = app_title
    return headers


def llm_api_url(base_url: str, path: str) -> str:
    base = (base_url or "").rstrip("/")
    p = "/" + str(path or "").lstrip("/")
    if base.endswith("/v1"):
        return f"{base}{p}"
    return f"{base}/v1{p}"


def resolve_llm_model(base_url: str) -> Optional[str]:
    global LLM_MODEL_CACHE
    if LLM_MODEL_CACHE:
        return LLM_MODEL_CACHE
    try:
        req = url_request.Request(llm_api_url(base_url, "/models"), headers=llm_headers())
        with url_request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8", "ignore"))
        models = data.get("data") or []
        model_ids = [str(m.get("id") or "").strip() for m in models if str(m.get("id") or "").strip()]

        preferred = [
            s.strip()
            for s in (os.getenv("LLM_MODEL_PREFER", "llama-3.1-8b-instant,llama-3.3-70b-versatile")).split(",")
            if s.strip()
        ]
        for want in preferred:
            for mid in model_ids:
                if mid == want or want in mid:
                    LLM_MODEL_CACHE = mid
                    return LLM_MODEL_CACHE

        # Fallback: choose first chat-capable text model, skip whisper/audio/moderation style ids.
        for mid in model_ids:
            low = mid.lower()
            if any(bad in low for bad in ("whisper", "tts", "transcribe", "moderation", "guard")):
                continue
            LLM_MODEL_CACHE = mid
            return LLM_MODEL_CACHE
    except Exception:
        return None
    return LLM_MODEL_CACHE


def build_llm_prompt(raw_text: str, containers: List[str], dates: List[str]) -> str:
    return (
        "Extract containerNo and date (MM/DD/YYYY) from OCR text. "
        "Use ISO 6346 as the reference standard. "
        "A valid container is owner(3 letters)+category(U/J/Z)+6 serial digits+1 check digit. "
        "If containerNo is not confidently ISO-valid, return an empty string for containerNo. "
        "Never invent values. Return strict JSON only with keys: containerNo, date."
        f"\n\nOCR TEXT:\n{raw_text[:1200]}"
        f"\n\nCANDIDATE CONTAINERS: {containers}"
        f"\nCANDIDATE DATES: {dates}"
    )


def normalize_llm_output(parsed: dict) -> dict:
    out = {
        "containerNo": normalize_container(str(parsed.get("containerNo", ""))),
        "date": str(parsed.get("date", "")).strip(),
    }
    if out["containerNo"] and not valid_container(out["containerNo"]):
        out["containerNo"] = ""
    if out["date"] and not valid_date(out["date"]):
        out["date"] = ""
    return out


def llm_postprocess_openai(
    raw_text: str, containers: List[str], dates: List[str], image_bytes: Optional[bytes]
) -> Tuple[Optional[dict], Optional[str]]:
    base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:18084").rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip() or resolve_llm_model(base_url)
    if not model:
        return None, "llm_model_unavailable"

    content = [{"type": "text", "text": build_llm_prompt(raw_text, containers, dates)}]
    if image_bytes and env_bool("LLM_INCLUDE_IMAGE", "1"):
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
        llm_api_url(base_url, "/chat/completions"),
        data=json.dumps(payload).encode("utf-8"),
        headers=llm_headers(),
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=int(os.getenv("LLM_TIMEOUT_SEC", "25"))) as res:
            body = json.loads(res.read().decode("utf-8", "ignore"))
        text = (
            (((body.get("choices") or [{}])[0].get("message") or {}).get("content"))
            if isinstance(body, dict)
            else ""
        )
        parsed = extract_json_object(text if isinstance(text, str) else "")
        if not parsed:
            return None, "llm_json_parse_failed"
        return normalize_llm_output(parsed), None
    except url_error.HTTPError as err:
        return None, f"llm_http_{err.code}"
    except Exception as err:
        return None, f"llm_error:{err}"


def llm_postprocess_gemini(
    raw_text: str, containers: List[str], dates: List[str], image_bytes: Optional[bytes], image_mime: str
) -> Tuple[Optional[dict], Optional[str]]:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        return None, "gemini_api_key_missing"

    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    parts = [{"text": build_llm_prompt(raw_text, containers, dates)}]
    if image_bytes and env_bool("LLM_INCLUDE_IMAGE", "1"):
        parts.append(
            {
                "inline_data": {
                    "mime_type": image_mime or "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
        )

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }

    req = url_request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=int(os.getenv("LLM_TIMEOUT_SEC", "25"))) as res:
            body = json.loads(res.read().decode("utf-8", "ignore"))

        text_bits: List[str] = []
        for cand in body.get("candidates") or []:
            for part in ((cand.get("content") or {}).get("parts") or []):
                t = part.get("text")
                if isinstance(t, str) and t.strip():
                    text_bits.append(t)

        parsed = extract_json_object("\n".join(text_bits))
        if not parsed:
            return None, "llm_json_parse_failed"
        return normalize_llm_output(parsed), None
    except url_error.HTTPError as err:
        return None, f"gemini_http_{err.code}"
    except Exception as err:
        return None, f"gemini_error:{err}"


def llm_postprocess(
    raw_text: str,
    containers: List[str],
    dates: List[str],
    image_bytes: Optional[bytes],
    image_mime: str,
) -> Tuple[Optional[dict], Optional[str]]:
    if not env_bool("ENABLE_LLM_POSTPROCESS", "1"):
        return None, "llm_disabled"

    provider = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    if provider in ("none", "off", "disabled"):
        return None, "llm_disabled"

    gemini_key_set = bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())
    if provider in ("", "auto"):
        provider = "gemini" if gemini_key_set else "openai"

    if provider in ("gemini", "google", "gemini_flash"):
        return llm_postprocess_gemini(raw_text, containers, dates, image_bytes, image_mime)

    out, err = llm_postprocess_openai(raw_text, containers, dates, image_bytes)
    if err == "llm_model_unavailable" and gemini_key_set:
        return llm_postprocess_gemini(raw_text, containers, dates, image_bytes, image_mime)
    return out, err


class RecordIn(BaseModel):
    containerNo: str = Field(min_length=1, max_length=32)
    date: str
    sourceFileName: Optional[str] = None
    corrected: bool = False


class LocalGroqConfigIn(BaseModel):
    apiKey: str = Field(min_length=8, max_length=256)


class LocalModeConfigIn(BaseModel):
    directImageToLlm: bool = False


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
        "ocrProvider": os.getenv("OCR_PROVIDER", "auto"),
        "llmProvider": os.getenv("LLM_PROVIDER", "auto"),
        "ocrLibrariesAvailable": bool(Image is not None and pytesseract is not None),
        "pdfParserAvailable": bool(PdfReader is not None or pdfplumber is not None or fitz is not None),
        "doctrAvailable": bool(DocumentFile is not None and ocr_predictor is not None),
        "ocrSpaceApiKeySet": bool(os.getenv("OCR_SPACE_API_KEY")),
        "llmApiKeySet": bool(os.getenv("LLM_API_KEY")),
        "geminiApiKeySet": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "directImageToLlm": env_bool("DIRECT_IMAGE_TO_LLM", "0"),
        "localControlApi": env_bool("ENABLE_LOCAL_CONTROL_API", "0"),
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

    file_sha256 = hashlib.sha256(raw).hexdigest()
    source_file_name = strip_extension(filename)
    file_type = "pdf" if is_pdf else normalize_file_type(Path(filename).suffix.lstrip("."))
    if file_type == "jpeg":
        file_type = "jpg"

    submission_id = str(uuid.uuid4())
    now = now_iso()

    conn = db_connect()
    prior_same_hash = conn.execute(
        "SELECT id FROM submissions WHERE file_sha256 = ? ORDER BY created_at DESC LIMIT 1",
        (file_sha256,),
    ).fetchone()
    duplicate_of = prior_same_hash["id"] if prior_same_hash else None

    conn.execute(
        """
        INSERT INTO submissions(
            id, source_file_name, file_type, classifier, status,
            uploaded_at, created_at, updated_at, file_sha256, dedupe_key,
            duplicate_of, fallback_date_used, fallback_date_value, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            submission_id,
            source_file_name,
            file_type,
            "other",
            "PROCESSING",
            now,
            now,
            now,
            file_sha256,
            f"sha:{file_sha256}",
            duplicate_of,
            0,
            None,
            "phase2_intake",
        ),
    )
    conn.execute(
        "INSERT INTO document_files(id, submission_id, original_filename, source_file_name, file_type, file_sha256, storage_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            submission_id,
            filename,
            source_file_name,
            file_type,
            file_sha256,
            None,
            now,
        ),
    )
    add_audit(conn, submission_id, "INTAKE_CREATED", "system", {"fileType": file_type, "sourceFileName": source_file_name})
    conn.commit()
    conn.close()

    temp_name = f"{file_sha256[:12]}_{filename}"
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

    if is_image and env_bool("DIRECT_IMAGE_TO_LLM", "0"):
        pipeline_notes.append("llm_direct_image_mode")

        llm_structured, llm_error = llm_postprocess(
            raw_text="",
            containers=[],
            dates=[],
            image_bytes=raw,
            image_mime=ctype or "image/jpeg",
        )
        if llm_structured:
            pipeline_notes.append("llm_postprocess")
        elif llm_error:
            pipeline_notes.append(llm_error)

        extracted_container = (llm_structured or {}).get("containerNo") or ""
        extracted_date = (llm_structured or {}).get("date") or dt.datetime.now().strftime("%m/%d/%Y")

        issues = []
        if not extracted_container:
            issues.append("iso_container_text_not_found")

        classifier = classify_initial_document(filename, "", [], [])
        dedupe_key = compute_dedupe_key(classifier, {"container_number": extracted_container, "event_date": extracted_date}, file_sha256)

        conn = db_connect()
        existing = conn.execute(
            "SELECT id FROM submissions WHERE id != ? AND (file_sha256 = ? OR dedupe_key = ?) ORDER BY created_at DESC LIMIT 1",
            (submission_id, file_sha256, dedupe_key),
        ).fetchone()
        dup = existing["id"] if existing else duplicate_of
        status = "DUPLICATE" if dup else "PROCESSING"
        conn.execute(
            "UPDATE submissions SET classifier = ?, status = ?, updated_at = ?, dedupe_key = ?, duplicate_of = ? WHERE id = ?",
            (classifier, status, now_iso(), dedupe_key, dup, submission_id),
        )
        add_audit(conn, submission_id, "INTAKE_CLASSIFIED", "system", {"classifier": classifier, "status": status})
        conn.commit()
        conn.close()

        return {
            "ok": True,
            "scanId": str(uuid.uuid4()),
            "submissionId": submission_id,
            "status": status,
            "classifier": classifier,
            "fileHash": file_sha256,
            "duplicateOf": dup,
            "extracted": {"containerNo": extracted_container, "date": extracted_date},
            "candidates": {"containerNos": [], "dates": []},
            "candidateDetails": {"containerNos": []},
            "issues": issues,
            "requiresReview": True,
            "sourceFileName": filename,
            "ocrMode": "llm_direct_image",
            "rawTextPreview": "",
            "pipeline": pipeline_notes,
        }

    tess_ok = False
    doctr_ok = False
    ocrspace_ok = False

    ocr_chain = resolve_ocr_provider_chain()
    for ocr_provider in ocr_chain:
        if ocr_provider == "ocrspace":
            ocr_inputs: List[Tuple[bytes, str, str, str]] = []
            if is_pdf:
                ocr_input = raw
                ocr_filename = filename
                ocr_content_type = ctype or "application/pdf"
                if image_for_ocr is not None and env_bool("OCR_SPACE_USE_RASTER_FOR_PDF", "0"):
                    raster = pil_to_jpeg_bytes(image_for_ocr)
                    if raster:
                        ocr_input = raster
                        ocr_filename = f"{Path(filename).stem}.jpg"
                        ocr_content_type = "image/jpeg"
                ocr_inputs.append((ocr_input, ocr_filename, ocr_content_type, "pdf"))
            else:
                if image_for_ocr is not None and env_bool("OCRSPACE_PREPROCESS", "1"):
                    ocr_inputs.extend(ocrspace_image_inputs(image_for_ocr, filename))
                else:
                    ocr_inputs.append((raw, filename, ctype or "image/jpeg", "orig"))

            seen_text = set()
            for ocr_input, ocr_filename, ocr_content_type, ocr_tag in ocr_inputs:
                ocrspace_texts, ok, err = run_ocrspace(ocr_input, ocr_filename, ocr_content_type)
                if ok and ocrspace_texts:
                    ocrspace_ok = True
                    note = "ocr_ocrspace" if ocr_tag == "orig" else f"ocr_ocrspace_{ocr_tag}"
                    pipeline_notes.append(note)
                    for txt in ocrspace_texts:
                        key = (txt or "").strip()
                        if key and key not in seen_text:
                            raw_text_parts.append(key)
                            seen_text.add(key)
                elif err:
                    pipeline_notes.append(err)

            if ocrspace_ok and env_bool("OCR_STOP_ON_FIRST_SUCCESS", "1"):
                break

        elif ocr_provider == "local":
            tesseract_texts, t_ok, tess_err = run_tesseract(image_for_ocr)
            if t_ok and tesseract_texts:
                tess_ok = True
                pipeline_notes.append("ocr_tesseract")
                raw_text_parts.extend(tesseract_texts)
            elif tess_err:
                pipeline_notes.append(tess_err)

            doctr_texts, d_ok, doctr_err = run_doctr(temp_path)
            if d_ok and doctr_texts:
                doctr_ok = True
                pipeline_notes.append("ocr_doctr")
                raw_text_parts.extend(doctr_texts)
            elif doctr_err and doctr_err not in ("doctr_disabled", "doctr_dependency_missing"):
                pipeline_notes.append(doctr_err)

            if (tess_ok or doctr_ok) and env_bool("OCR_STOP_ON_FIRST_SUCCESS", "1"):
                break

    raw_text_parts.append(filename)
    raw_text = "\n".join([p for p in raw_text_parts if p]).strip()

    containers = extract_container_candidates(raw_text)
    dates = extract_date_candidates(raw_text)

    llm_image_bytes = raw if is_image else pil_to_jpeg_bytes(image_for_ocr)
    llm_image_mime = ctype if is_image else "image/jpeg"

    llm_structured, llm_error = llm_postprocess(raw_text, containers, dates, llm_image_bytes, llm_image_mime)
    if llm_structured:
        pipeline_notes.append("llm_postprocess")
    elif llm_error:
        pipeline_notes.append(llm_error)

    valid_containers = [c for c in containers if valid_container(c)]
    fallback_container = valid_containers[0] if valid_containers else ""
    extracted_container = (llm_structured or {}).get("containerNo") or fallback_container

    llm_date = (llm_structured or {}).get("date") or ""
    if dates:
        extracted_date = llm_date if llm_date in dates else dates[0]
    else:
        extracted_date = dt.datetime.now().strftime("%m/%d/%Y")

    issues = []
    if not valid_containers and not extracted_container:
        issues.append("iso_container_text_not_found")
    elif len(valid_containers) > 1:
        issues.append("multiple_container_matches")

    if not dates and not valid_date(extracted_date):
        issues.append("invalid_or_missing_date")
    elif len(dates) > 1:
        issues.append("multiple_date_matches")

    if not tess_ok and not doctr_ok and not ocrspace_ok and not (is_pdf and raw_text):
        issues.append("ocr_engine_unavailable")

    candidate_details = [{"value": c, "iso6346Valid": iso6346_is_valid(c)} for c in containers]

    classifier = classify_initial_document(filename, raw_text, valid_containers, dates)
    dedupe_payload = {
        "container_number": extracted_container,
        "event_date": extracted_date,
        "transaction_date": extracted_date,
    }
    dedupe_key = compute_dedupe_key(classifier, dedupe_payload, file_sha256)

    conn = db_connect()
    existing = conn.execute(
        "SELECT id FROM submissions WHERE id != ? AND (file_sha256 = ? OR dedupe_key = ?) ORDER BY created_at DESC LIMIT 1",
        (submission_id, file_sha256, dedupe_key),
    ).fetchone()
    dup = existing["id"] if existing else duplicate_of
    status = "DUPLICATE" if dup else "PROCESSING"

    extraction_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO extraction_results(id, submission_id, classifier, raw_text, confidence_summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (extraction_id, submission_id, classifier, raw_text[:4000], None, now_iso()),
    )
    conn.execute(
        "INSERT INTO extracted_fields(id, submission_id, extraction_result_id, field_name, field_value, confidence, is_required, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), submission_id, extraction_id, "container_number", extracted_container or None, None, 1 if classifier == "container" else 0, "intake_scan", now_iso()),
    )
    conn.execute(
        "INSERT INTO extracted_fields(id, submission_id, extraction_result_id, field_name, field_value, confidence, is_required, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), submission_id, extraction_id, "event_date", extracted_date or None, None, 1 if classifier == "container" else 0, "intake_scan", now_iso()),
    )
    conn.execute(
        "UPDATE submissions SET classifier = ?, status = ?, updated_at = ?, dedupe_key = ?, duplicate_of = ?, fallback_date_used = ?, fallback_date_value = ? WHERE id = ?",
        (classifier, status, now_iso(), dedupe_key, dup, 1 if not dates else 0, extracted_date if not dates else None, submission_id),
    )
    add_audit(conn, submission_id, "INTAKE_CLASSIFIED", "system", {"classifier": classifier, "status": status})
    add_audit(conn, submission_id, "INTAKE_EXTRACTION", "system", {"issues": issues, "pipeline": pipeline_notes})
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "scanId": str(uuid.uuid4()),
        "submissionId": submission_id,
        "status": status,
        "classifier": classifier,
        "fileHash": file_sha256,
        "duplicateOf": dup,
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


@app.get("/control/local/runtime-info")
def get_local_runtime_info():
    if not env_bool("ENABLE_LOCAL_CONTROL_API", "0"):
        raise HTTPException(status_code=403, detail="Local control API disabled")

    local_backend_url = read_text_if_exists(LOCAL_BACKEND_URL_PATH)
    public_backend_url = read_text_if_exists(PUBLIC_BACKEND_URL_PATH)
    meta = parse_simple_meta(read_text_if_exists(PUBLIC_BACKEND_META_PATH))

    latest_from_log = extract_latest_tunnel_url(TUNNEL_LOG_PATH)
    if latest_from_log:
        public_backend_url = latest_from_log

    if not public_backend_url and meta.get("backendUrl"):
        public_backend_url = meta.get("backendUrl", "")


    return {
        "ok": True,
        "runtime": {
            "localBackendUrl": local_backend_url,
            "publicBackendUrl": public_backend_url,
            "generatedAt": meta.get("generatedAt", ""),
            "frontendUrl": meta.get("frontendUrl", ""),
            "tunnelLogTail": tail_text_if_exists(TUNNEL_LOG_PATH, max_lines=12),
        },
    }


@app.post("/control/local/groq-key")
def set_local_groq_key(payload: LocalGroqConfigIn):
    if not env_bool("ENABLE_LOCAL_CONTROL_API", "0"):
        raise HTTPException(status_code=403, detail="Local control API disabled")

    key = (payload.apiKey or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Groq key is required")

    env_path = ROOT / ".env"
    upsert_env_values(
        env_path,
        {
            "LLM_API_KEY": key,
            "LLM_PROVIDER": "openai",
            "LLM_BASE_URL": "https://api.groq.com/openai",
            "LLM_MODEL": os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
            "LLM_INCLUDE_IMAGE": "1",
            "OCR_PROVIDER": "auto",
            "OCR_FALLBACK_LOCAL": "1",
            "ENABLE_LLM_POSTPROCESS": "1",
        },
    )

    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass

    os.environ["LLM_API_KEY"] = key
    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["LLM_BASE_URL"] = "https://api.groq.com/openai"
    os.environ["LLM_MODEL"] = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    os.environ["LLM_INCLUDE_IMAGE"] = "1"
    os.environ["OCR_PROVIDER"] = "auto"
    os.environ["OCR_FALLBACK_LOCAL"] = "1"
    os.environ["ENABLE_LLM_POSTPROCESS"] = "1"
    global LLM_MODEL_CACHE
    LLM_MODEL_CACHE = None

    return {
        "ok": True,
        "message": "Groq key saved to .env",
        "path": str(env_path),
        "providers": {"ocr": "ocrspace", "llm": "groq"},
    }


@app.post("/control/local/mode")
def set_local_mode(payload: LocalModeConfigIn):
    if not env_bool("ENABLE_LOCAL_CONTROL_API", "0"):
        raise HTTPException(status_code=403, detail="Local control API disabled")

    direct = bool(payload.directImageToLlm)
    env_path = ROOT / ".env"
    upsert_env_values(
        env_path,
        {
            "DIRECT_IMAGE_TO_LLM": "1" if direct else "0",
            "LLM_INCLUDE_IMAGE": "1" if direct else os.getenv("LLM_INCLUDE_IMAGE", "0"),
        },
    )

    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass

    os.environ["DIRECT_IMAGE_TO_LLM"] = "1" if direct else "0"
    if direct:
        os.environ["LLM_INCLUDE_IMAGE"] = "1"

    return {
        "ok": True,
        "message": "Mode updated",
        "mode": {"directImageToLlm": direct},
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


# -----------------------------
# Sprint 3 Phase 1 foundations
# -----------------------------

SUPPORTED_FILE_TYPES = {"pdf", "png", "jpg", "jpeg", "webp", "gif", "tiff", "bmp"}
SUPPORTED_CLASSIFIERS = {"container", "receipt", "other"}
REQUIRED_FIELDS_BY_CLASSIFIER = {
    "container": ["container_number", "event_date"],
    "receipt": ["transaction_date"],
    "other": [],
}
CONFIDENCE_THRESHOLD = 0.80


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def strip_extension(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "upload"
    return re.sub(r"\.[A-Za-z0-9]+$", "", text)


def normalize_file_type(value: str) -> str:
    return (value or "").strip().lower().replace(".", "")


def normalize_classifier(value: str) -> str:
    text = (value or "other").strip().lower()
    return text if text in SUPPORTED_CLASSIFIERS else "other"


def compute_sha256(file_b64: Optional[str], source_name: str, file_type: str, extracted: Dict[str, Any]) -> str:
    if file_b64:
        raw = base64.b64decode(file_b64)
        return hashlib.sha256(raw).hexdigest()
    fallback = json.dumps({"source": source_name, "fileType": file_type, "extracted": extracted}, sort_keys=True)
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()


def compute_dedupe_key(classifier: str, extracted: Dict[str, Any], file_sha256: str) -> str:
    if classifier == "container":
        c = (extracted.get("container_number") or "").strip().upper()
        d = (extracted.get("event_date") or "").strip()
        return f"container:{c}|{d}" if c or d else f"sha:{file_sha256}"
    if classifier == "receipt":
        d = (extracted.get("transaction_date") or "").strip()
        v = (extracted.get("vendor_name") or "").strip().lower()
        a = str(extracted.get("amount") or "").strip()
        return f"receipt:{d}|{v}|{a}" if d or v or a else f"sha:{file_sha256}"
    return f"sha:{file_sha256}"


def classify_initial_document(filename: str, raw_text: str, containers: List[str], dates: List[str]) -> str:
    if containers:
        return "container"
    text = f"{filename}\n{raw_text}".lower()
    if any(k in text for k in ["receipt", "invoice", "purchase", "transaction"]):
        return "receipt"
    if dates:
        return "receipt"
    return "other"


def add_audit(conn: sqlite3.Connection, submission_id: Optional[str], action: str, actor: str, details: Dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit_logs(id, submission_id, action, actor, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), submission_id, action, actor, json.dumps(details), now_iso()),
    )


def evaluate_rules(classifier: str, extracted: Dict[str, Any], confidence: Dict[str, float], uploaded_at_iso: str, duplicate_found: bool) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    working = dict(extracted)
    required = REQUIRED_FIELDS_BY_CLASSIFIER.get(classifier, [])

    def push(rule_id: str, passed: bool, reason: str, severity: str):
        rules.append({"rule_id": rule_id, "passed": passed, "reason": reason, "severity": severity})

    if classifier == "other":
        push("unsupported_document_rule", False, "Unsupported classifier routed to review.", "error")
    else:
        push("unsupported_document_rule", True, "Classifier is supported.", "info")

    # Date fallback rule
    date_key = "event_date" if classifier == "container" else "transaction_date" if classifier == "receipt" else None
    fallback_used = False
    fallback_value = None
    if date_key:
        if not (working.get(date_key) or "").strip():
            fallback_value = dt.datetime.fromisoformat(uploaded_at_iso).strftime("%m/%d/%Y")
            working[date_key] = fallback_value
            fallback_used = True
            push("date_fallback_rule", True, f"Missing {date_key}; applied upload timestamp fallback.", "warn")
        else:
            push("date_fallback_rule", True, f"{date_key} present; no fallback used.", "info")
    else:
        push("date_fallback_rule", True, "No date requirement for this classifier.", "info")

    missing = [f for f in required if not (working.get(f) or "").strip()]
    if missing:
        push("required_field_rule", False, f"Missing required fields: {', '.join(missing)}", "error")
        push("missing_data_rule", False, "Manual input required for missing fields.", "error")
    else:
        push("required_field_rule", True, "All required fields present.", "info")
        push("missing_data_rule", True, "No missing required fields.", "info")

    low_conf = []
    for f in required:
        score = confidence.get(f)
        if score is not None and float(score) < CONFIDENCE_THRESHOLD:
            low_conf.append(f"{f}<{CONFIDENCE_THRESHOLD}")
    if low_conf:
        push("confidence_threshold_rule", False, f"Low confidence required fields: {', '.join(low_conf)}", "warn")
    else:
        push("confidence_threshold_rule", True, "Required fields satisfy confidence threshold or no score provided.", "info")

    if duplicate_found:
        push("duplicate_detection_rule", False, "Potential duplicate detected.", "warn")
    else:
        push("duplicate_detection_rule", True, "No duplicate detected.", "info")

    any_error = any((not r["passed"] and r["severity"] == "error") for r in rules)
    any_warn_fail = any((not r["passed"] and r["severity"] == "warn") for r in rules)

    if duplicate_found:
        status = "DUPLICATE"
    elif any_error or any_warn_fail:
        status = "NEEDS_REVIEW"
    else:
        status = "APPROVED"

    push("audit_rule", True, "Changes and transitions recorded in audit_logs.", "info")

    return rules, {
        "status": status,
        "normalized_extracted": working,
        "fallback_date_used": fallback_used,
        "fallback_date_value": fallback_value,
    }


def fetch_submission_bundle(submission_id: str) -> Optional[Dict[str, Any]]:
    conn = db_connect()
    sub = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    if not sub:
        conn.close()
        return None

    extraction = conn.execute("SELECT * FROM extraction_results WHERE submission_id = ? ORDER BY created_at DESC LIMIT 1", (submission_id,)).fetchone()
    fields = conn.execute("SELECT field_name, field_value, confidence, is_required, source FROM extracted_fields WHERE submission_id = ?", (submission_id,)).fetchall()
    reviews = conn.execute("SELECT * FROM review_tasks WHERE submission_id = ? ORDER BY created_at DESC", (submission_id,)).fetchall()
    verified = conn.execute("SELECT * FROM verified_records WHERE submission_id = ? ORDER BY approved_at DESC LIMIT 1", (submission_id,)).fetchone()
    audit = conn.execute("SELECT * FROM audit_logs WHERE submission_id = ? ORDER BY created_at DESC", (submission_id,)).fetchall()
    conn.close()

    return {
        "submission": dict(sub),
        "extractionResult": dict(extraction) if extraction else None,
        "extractedFields": [dict(f) for f in fields],
        "reviewTasks": [dict(r) for r in reviews],
        "verifiedRecord": dict(verified) if verified else None,
        "audit": [dict(a) for a in audit],
    }


class SubmissionIn(BaseModel):
    submissionId: Optional[str] = None
    sourceFileName: str
    fileType: str
    classifier: Optional[str] = "other"
    originalFileName: Optional[str] = None
    extracted: Optional[Dict[str, Any]] = None
    confidence: Optional[Dict[str, float]] = None
    rawText: Optional[str] = None
    fileContentBase64: Optional[str] = None
    uploadedAt: Optional[str] = None


class ReviewActionIn(BaseModel):
    actor: Optional[str] = "user"
    corrections: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


class ApproveIn(BaseModel):
    actor: Optional[str] = "admin"
    verifiedFields: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


class RejectIn(BaseModel):
    actor: Optional[str] = "admin"
    reason: str


@app.post("/submit")
def submit_document(payload: SubmissionIn):
    source_file_name = strip_extension(payload.sourceFileName)
    file_type = normalize_file_type(payload.fileType)
    classifier = normalize_classifier(payload.classifier or "other")
    extracted = payload.extracted or {}
    confidence = payload.confidence or {}
    uploaded_at = payload.uploadedAt or now_iso()

    if file_type not in SUPPORTED_FILE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported fileType '{file_type}'.")

    submission_id = (payload.submissionId or "").strip() or str(uuid.uuid4())
    now = now_iso()
    file_sha256 = compute_sha256(payload.fileContentBase64, source_name=source_file_name, file_type=file_type, extracted=extracted)
    dedupe_key = compute_dedupe_key(classifier, extracted, file_sha256)

    conn = db_connect()
    existing_submission = conn.execute("SELECT id FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    existing = conn.execute(
        "SELECT id FROM submissions WHERE id != ? AND (file_sha256 = ? OR dedupe_key = ?) ORDER BY created_at DESC LIMIT 1",
        (submission_id, file_sha256, dedupe_key),
    ).fetchone()
    duplicate_of = existing["id"] if existing else None

    rule_results, eval_out = evaluate_rules(
        classifier=classifier,
        extracted=extracted,
        confidence=confidence,
        uploaded_at_iso=uploaded_at,
        duplicate_found=bool(duplicate_of),
    )

    status = eval_out["status"]
    normalized = eval_out["normalized_extracted"]

    if existing_submission:
        conn.execute(
            """
            UPDATE submissions
               SET source_file_name = ?, file_type = ?, classifier = ?, status = ?,
                   uploaded_at = ?, updated_at = ?, file_sha256 = ?, dedupe_key = ?,
                   duplicate_of = ?, fallback_date_used = ?, fallback_date_value = ?
             WHERE id = ?
            """,
            (
                source_file_name,
                file_type,
                classifier,
                status,
                uploaded_at,
                now,
                file_sha256,
                dedupe_key,
                duplicate_of,
                1 if eval_out["fallback_date_used"] else 0,
                eval_out["fallback_date_value"],
                submission_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO submissions(
                id, source_file_name, file_type, classifier, status,
                uploaded_at, created_at, updated_at, file_sha256, dedupe_key,
                duplicate_of, fallback_date_used, fallback_date_value, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                source_file_name,
                file_type,
                classifier,
                status,
                uploaded_at,
                now,
                now,
                file_sha256,
                dedupe_key,
                duplicate_of,
                1 if eval_out["fallback_date_used"] else 0,
                eval_out["fallback_date_value"],
                "",
            ),
        )

    doc_file_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO document_files(id, submission_id, original_filename, source_file_name, file_type, file_sha256, storage_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doc_file_id,
            submission_id,
            payload.originalFileName,
            source_file_name,
            file_type,
            file_sha256,
            None,
            now,
        ),
    )

    extraction_id = str(uuid.uuid4())
    confidence_summary = None
    if confidence:
        vals = [float(v) for v in confidence.values()]
        confidence_summary = sum(vals) / len(vals)

    conn.execute(
        "INSERT INTO extraction_results(id, submission_id, classifier, raw_text, confidence_summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (extraction_id, submission_id, classifier, payload.rawText, confidence_summary, now),
    )

    required_fields = set(REQUIRED_FIELDS_BY_CLASSIFIER.get(classifier, []))
    for field_name, field_value in normalized.items():
        conf = confidence.get(field_name)
        conn.execute(
            "INSERT INTO extracted_fields(id, submission_id, extraction_result_id, field_name, field_value, confidence, is_required, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                submission_id,
                extraction_id,
                field_name,
                str(field_value) if field_value is not None else None,
                conf,
                1 if field_name in required_fields else 0,
                "extraction",
                now,
            ),
        )

    if status in ("NEEDS_REVIEW", "DUPLICATE"):
        reasons = [r["rule_id"] for r in rule_results if not r["passed"]]
        conn.execute(
            "INSERT INTO review_tasks(id, submission_id, reason_code, status, assigned_to, created_at, resolved_at, resolution_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), submission_id, ",".join(reasons) or "manual_review", "OPEN", None, now, None, None),
        )

    if status == "APPROVED":
        conn.execute(
            "INSERT INTO verified_records(id, submission_id, classifier, normalized_payload, approved_by, approved_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), submission_id, classifier, json.dumps(normalized), "system", now),
        )

        if classifier == "container":
            record_container = normalize_container(normalized.get("container_number") or "")
            record_date = (normalized.get("event_date") or "").strip()
            if valid_container(record_container) and valid_date(record_date):
                exists_record = conn.execute(
                    "SELECT id FROM records WHERE containerNo = ? AND date = ? AND sourceFileName = ? ORDER BY id DESC LIMIT 1",
                    (record_container, record_date, source_file_name),
                ).fetchone()
                if not exists_record:
                    conn.execute(
                        "INSERT INTO records(containerNo, date, sourceFileName, corrected, createdAt) VALUES (?, ?, ?, ?, ?)",
                        (record_container, record_date, source_file_name, 1, now),
                    )

    add_audit(conn, submission_id, "SUBMIT", "user", {"sourceFileName": source_file_name, "fileType": file_type, "classifier": classifier})
    add_audit(conn, submission_id, "VALIDATE", "system", {"rules": rule_results, "status": status})
    add_audit(conn, submission_id, "STATUS_ROUTE", "system", {"status": status, "duplicateOf": duplicate_of})

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "submissionId": submission_id,
        "status": status,
        "ruleResults": rule_results,
        "duplicateOf": duplicate_of,
        "normalizedExtracted": normalized,
    }


@app.get("/submission/{submission_id}")
def get_submission(submission_id: str):
    data = fetch_submission_bundle(submission_id)
    if not data:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"ok": True, **data}


@app.get("/submissions")
def list_submissions(status: Optional[str] = None):
    conn = db_connect()
    if status:
        rows = conn.execute(
            "SELECT id, source_file_name, file_type, classifier, status, created_at, updated_at, duplicate_of FROM submissions WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, source_file_name, file_type, classifier, status, created_at, updated_at, duplicate_of FROM submissions ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return {"ok": True, "submissions": [dict(r) for r in rows]}


@app.post("/review/{submission_id}")
def review_submission(submission_id: str, payload: ReviewActionIn):
    corrections = payload.corrections or {}
    actor = payload.actor or "user"
    conn = db_connect()
    sub = conn.execute("SELECT id, status FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")

    now = now_iso()
    for field_name, field_value in corrections.items():
        current = conn.execute(
            "SELECT id FROM extracted_fields WHERE submission_id = ? AND field_name = ? ORDER BY created_at DESC LIMIT 1",
            (submission_id, field_name),
        ).fetchone()
        if current:
            conn.execute(
                "UPDATE extracted_fields SET field_value = ?, source = ? WHERE id = ?",
                (str(field_value) if field_value is not None else None, "manual_review", current["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO extracted_fields(id, submission_id, extraction_result_id, field_name, field_value, confidence, is_required, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), submission_id, None, field_name, str(field_value), None, 0, "manual_review", now),
            )

    conn.execute("UPDATE submissions SET updated_at = ?, status = ? WHERE id = ?", (now, "NEEDS_REVIEW", submission_id))
    conn.execute(
        "UPDATE review_tasks SET status = ?, resolution_note = ?, resolved_at = ? WHERE submission_id = ? AND status = 'OPEN'",
        ("IN_PROGRESS", payload.note, None, submission_id),
    )
    add_audit(conn, submission_id, "REVIEW_EDIT", actor, {"corrections": corrections, "note": payload.note})
    conn.commit()
    conn.close()

    return {"ok": True, "submissionId": submission_id, "status": "NEEDS_REVIEW"}


@app.post("/approve/{submission_id}")
def approve_submission(submission_id: str, payload: ApproveIn):
    actor = payload.actor or "admin"
    conn = db_connect()
    sub = conn.execute("SELECT id, classifier FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")

    now = now_iso()
    if payload.verifiedFields:
        normalized_payload = payload.verifiedFields
    else:
        rows = conn.execute("SELECT field_name, field_value FROM extracted_fields WHERE submission_id = ?", (submission_id,)).fetchall()
        normalized_payload = {r["field_name"]: r["field_value"] for r in rows}

    existing = conn.execute("SELECT id FROM verified_records WHERE submission_id = ?", (submission_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE verified_records SET classifier = ?, normalized_payload = ?, approved_by = ?, approved_at = ? WHERE id = ?",
            (sub["classifier"], json.dumps(normalized_payload), actor, now, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO verified_records(id, submission_id, classifier, normalized_payload, approved_by, approved_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), submission_id, sub["classifier"], json.dumps(normalized_payload), actor, now),
        )

    conn.execute("UPDATE submissions SET status = ?, updated_at = ? WHERE id = ?", ("APPROVED", now, submission_id))
    conn.execute(
        "UPDATE review_tasks SET status = ?, resolved_at = ?, resolution_note = ? WHERE submission_id = ? AND status IN ('OPEN','IN_PROGRESS')",
        ("RESOLVED", now, payload.note, submission_id),
    )
    add_audit(conn, submission_id, "APPROVE", actor, {"note": payload.note})
    conn.commit()
    conn.close()
    return {"ok": True, "submissionId": submission_id, "status": "APPROVED"}


@app.post("/reject/{submission_id}")
def reject_submission(submission_id: str, payload: RejectIn):
    actor = payload.actor or "admin"
    conn = db_connect()
    sub = conn.execute("SELECT id FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")

    now = now_iso()
    conn.execute("UPDATE submissions SET status = ?, updated_at = ? WHERE id = ?", ("REJECTED", now, submission_id))
    conn.execute(
        "UPDATE review_tasks SET status = ?, resolved_at = ?, resolution_note = ? WHERE submission_id = ? AND status IN ('OPEN','IN_PROGRESS')",
        ("REJECTED", now, payload.reason, submission_id),
    )
    add_audit(conn, submission_id, "REJECT", actor, {"reason": payload.reason})
    conn.commit()
    conn.close()
    return {"ok": True, "submissionId": submission_id, "status": "REJECTED"}


@app.get("/admin/submissions")
def admin_submissions(status: Optional[str] = None):
    return list_submissions(status=status)


@app.get("/admin/flagged")
def admin_flagged():
    conn = db_connect()
    rows = conn.execute(
        "SELECT id, source_file_name, file_type, classifier, status, created_at, duplicate_of FROM submissions WHERE status IN ('NEEDS_REVIEW','DUPLICATE') ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return {"ok": True, "submissions": [dict(r) for r in rows]}


@app.get("/admin/audit")
def admin_audit(submissionId: Optional[str] = None, limit: int = 200):
    conn = db_connect()
    if submissionId:
        rows = conn.execute(
            "SELECT id, submission_id, action, actor, details, created_at FROM audit_logs WHERE submission_id = ? ORDER BY created_at DESC LIMIT ?",
            (submissionId, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, submission_id, action, actor, details, created_at FROM audit_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return {"ok": True, "audit": [dict(r) for r in rows]}
