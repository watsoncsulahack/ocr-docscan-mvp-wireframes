# Phase 0 Baseline Contract

## Objective
Establish a shared, testable contract before implementation so Sprint 3 can be built in controlled phases.

## Source References
- Sprint 3 formal report (`Team_Project_Sprint_3-2...pdf`, dated Apr 26 2026)
- Sprint 3 technical spec (`sprint3---...md`)

---

## 1) Canonical Workflow Contract
1. Submit document (image/PDF/camera)
2. Extract and classify
3. Validate against business rules
4. Route to:
   - Approved path (store verified)
   - Needs Review path (manual correction)
5. Finalize verified record
6. Log all actions in audit log

---

## 2) Document Contract (file type + classifier)
### A) File Type (technical)
`fileType` identifies the actual file format, for example:
- `pdf`
- `png`
- `jpg` / `jpeg`

### B) Source File Name
`sourceFileName` should be normalized to filename **without extension**.

### C) Classifier (semantic)
`classifier` indicates document meaning:
- `container`
- `receipt`
- `other`

Required fields by classifier:
- `container`: `container_number`, `event_date`
- `receipt`: `transaction_date`
- `other`: route to review as unsupported

Optional receipt fields:
- `vendor_name`
- `amount`

---

## 3) Submission Status Contract
Allowed statuses:
- `PROCESSING`
- `NEEDS_REVIEW`
- `APPROVED`
- `REJECTED`
- `DUPLICATE`

Transition intent:
- New submission starts `PROCESSING`
- Validation promotes to `APPROVED` or `NEEDS_REVIEW` or `DUPLICATE`
- Review action may move `NEEDS_REVIEW` → `APPROVED` or `REJECTED`

---

## 4) Business Rule Contract
1. Required Field Rule
2. Confidence Threshold Rule
3. Missing Data Rule
4. Date Fallback Rule (use upload timestamp with fallback marker)
5. Duplicate Detection Rule (hash and/or key-field match)
6. Unsupported Document Rule
7. Audit Rule (all changes/actions logged)

Each rule must emit:
- `rule_id`
- `passed` boolean
- `reason`
- `severity` (`info|warn|error`)

---

## 5) API Contract (Phase 0 shape)
### Submission
- `POST /submit`
- `GET /submission/{id}`
- `GET /submissions`

### Extraction
- `POST /scan` (extended to include classification + confidence + structured fields)

### Review
- `POST /review/{id}`
- `POST /approve/{id}`
- `POST /reject/{id}`

### Admin
- `GET /admin/submissions`
- `GET /admin/flagged`
- `GET /admin/audit`

---

## 6) Local-First Runtime Contract (VM-Oriented)
Primary operator mode for Edray privacy:
- Repo is pulled into VM.
- Backend + OCR dependencies run locally.
- Storage remains local (SQLite/local volume initially).
- Outbound network calls disabled by default in local mode.
- Optional cloud features require explicit opt-in flags.

Suggested environment flags (to implement in later phases):
- `OCR_MODE=local|cloud`
- `LLM_MODE=local|cloud|off`
- `EGRESS_POLICY=deny|allowlist`
- `AUDIT_STRICT=true|false`

---

## 7) Phase 0 Definition of Done
Phase 0 is complete when:
1. This contract and phased plan are committed on a Sprint 3 branch.
2. Team agrees on statuses, rules, and endpoint shape.
3. Local VM operation model is documented and accepted as primary dev/test mode.
4. Next implementation starts from Phase 1 data-model tasks.

---

## 8) Session Reset Handoff
If starting fresh:
1. Read this file.
2. Read `docs/SPRINT3_PHASED_BUILD_PLAN.md`.
3. Continue with Phase 1 implementation tasks.
