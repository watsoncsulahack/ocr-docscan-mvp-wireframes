# Phase 1.5 UI Screens (Implemented)

This phase provides a working user-facing UI flow for testing:

1. `upload.html`
   - choose PDF/image or camera capture
   - backend is auto-detected for local/offline mode
   - process selected file

2. `processing.html`
   - scanning progress steps
   - transition to review when scan completes

3. `review.html`
   - heading text: **Review items below**
   - color confidence dots per field:
     - green = good
     - yellow = review
     - red = fix required
   - button text: **Re-Run Scan**
   - blocked submit when yellow/red exists with error:
     - **Review these items before submitting.**

4. `confirmation.html`
   - submission success details

## Current scope
- User-first review flow for container fields
- Minimal confidence UI semantics
- Submit to backend `/submit`

## Deferred to later phase
- Full admin screens and escalation flows
- Advanced confidence calibration and policy tuning
