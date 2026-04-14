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

        return {
            "ok": True,
            "scanId": str(uuid.uuid4()),
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
        # If OCR found no explicit date, default to current date for deterministic MVP behavior.
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
