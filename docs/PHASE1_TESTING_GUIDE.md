# Phase 1 Testing Guide (Fedora VM, endpoint-by-endpoint)

This validates Sprint 3 Phase 1 data/persistence/audit foundations.

## 1) Start backend locally
From repo root:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Keep this terminal running.

## 2) Run isolated endpoint tests
Open a second terminal:

```bash
cd /path/to/ocr-docscan-mvp-wireframes
chmod +x tests/phase1/*.sh
```

Run each script one-by-one:

```bash
bash tests/phase1/00_health.sh
bash tests/phase1/01_submit_endpoint.sh
bash tests/phase1/02_get_submission_endpoint.sh
bash tests/phase1/03_list_submissions_endpoint.sh
bash tests/phase1/04_review_endpoint.sh
bash tests/phase1/02_get_submission_endpoint.sh
bash tests/phase1/05_approve_endpoint.sh
bash tests/phase1/06_admin_flagged_endpoint.sh
bash tests/phase1/07_admin_audit_endpoint.sh
```

## 3) Expected behavior
- `01_submit` should return a `submissionId` and `status` (likely `NEEDS_REVIEW` from the test payload).
- `02_get_submission` should show:
  - submission metadata
  - extracted fields
  - review task (if flagged)
  - audit entries
- `04_review` should apply corrections and keep review flow active.
- `05_approve` should move status to `APPROVED` and create/update a verified record.
- `07_admin_audit` should show action trail (submit, validate, route, review edit, approve).

## 4) Notes
- `fileType` is technical file type (`pdf/png/jpg/...`).
- `classifier` is semantic type (`container/receipt/other`).
- `sourceFileName` is normalized by backend to filename without extension.

## 5) Troubleshooting
- If scripts cannot connect, confirm backend is running on `127.0.0.1:8000`.
- To target a different URL:
  ```bash
  BASE_URL=http://<host>:<port> bash tests/phase1/00_health.sh
  ```
