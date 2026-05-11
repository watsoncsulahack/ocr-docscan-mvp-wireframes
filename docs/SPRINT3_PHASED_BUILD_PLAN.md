# Sprint 3 Phased Build Plan (Local-First, Edray-Aligned)

## Purpose
This plan stages implementation so each phase can be validated before moving forward. It is based on:
- `Team_Project_Sprint_3-2...pdf` (formal Sprint 3 report)
- `sprint3---...md` (Sprint 3 build specification)

## Guiding Constraints
1. Preserve current OCR MVP behavior while extending it.
2. Favor local/offline execution to reduce data leakage risk.
3. Add strict validation, review routing, and auditability.
4. Keep each phase testable and reversible.

---

## Phase 0 — Baseline + Contracts (current phase)
- Freeze scope and define canonical status model.
- Define document type schema and validation rules contract.
- Define API contract for submission/review/admin flows.
- Define local-first runtime profile for VM testing.
- Add acceptance checklist for all downstream phases.

**Gate to pass:**
- Team agrees on statuses/rules/endpoints and test matrix.
- Local VM setup path is documented and reproducible.

## Phase 1 — Data Model + Persistence
- Add/confirm core entities: Submission, DocumentFile, ExtractionResult, ExtractedField, ReviewTask, VerifiedRecord, AuditLog.
- Add migration/init scripts and indexes.
- Add duplicate-check keys (hash + business key strategy).

**Gate to pass:**
- CRUD and status transitions persist correctly.
- Audit records exist for all state-changing actions.

## Phase 2 — Submission Intake + File Lifecycle
- Robust file intake for image/PDF/camera capture.
- Submission creation + deterministic file IDs/hashes.
- Initial classification stage hooked into submission lifecycle.

**Gate to pass:**
- Valid files create submission records.
- Duplicate candidates are flagged predictably.

## Phase 3 — Extraction + Classification
- Extend `/scan` flow to produce structured extraction output with confidence metadata.
- Classify supported types: container doc and receipt/proof doc.
- Route unsupported/low-confidence cases to review.

**Gate to pass:**
- Golden samples produce expected fields and confidence outputs.

## Phase 4 — Validation Rules Engine
Implement required rules:
- Required Field
- Confidence Threshold
- Missing Data
- Date Fallback
- Duplicate Detection
- Unsupported Document
- Audit Rule

**Gate to pass:**
- Rule matrix test passes for all rule branches.

## Phase 5 — Review Workflow
- User/admin correction flow.
- Approve/reject actions with reasons.
- Review task lifecycle and ownership.

**Gate to pass:**
- A flagged submission can be corrected and finalized end-to-end.

## Phase 6 — Admin Panel
- All submissions view, status filters, flagged queue, duplicate queue.
- Audit log explorer and submission timeline.

**Gate to pass:**
- Admin can process flagged queue without DB/manual intervention.

## Phase 7 — End-to-End Hardening
- Regression suite for submit → scan → validate → review → verify.
- Fail-safe behavior for OCR/parser errors.
- Local-only mode verification (no external egress when disabled).

**Gate to pass:**
- E2E suite green in VM/local mode.

## Phase 8 — Final Containerization (last)
- Build single Docker image for frontend + backend + OCR dependencies + local storage.
- Add runtime flags for:
  - strict local/offline mode
  - optional cloud augmentation (explicit opt-in)
- Add operator runbook.

**Gate to pass:**
- One-command startup in VM.
- Complete offline ingestion/review flow works.

---

## Recommended Validation Rhythm
- Finish one phase only after passing that phase gate.
- Tag checkpoint commits (e.g., `phase-1-pass`, `phase-2-pass`).
- Keep a short test evidence log per phase.

## Branch Strategy
- Working branch: `sprint3/phase0-baseline-local-first`
- Continue sequentially with focused PRs/commits per phase.

## Handoff Note
If a new OpenClaw session is started, begin by reading:
1. `docs/SPRINT3_PHASED_BUILD_PLAN.md`
2. `docs/PHASE0_BASELINE_CONTRACT.md`
