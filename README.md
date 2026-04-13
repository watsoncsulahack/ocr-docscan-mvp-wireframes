# OCR Doc Scan MVP Wireframes (Static HTML)

This repository contains static HTML wireframes for the 5 requested screens:

1. Upload (`upload.html`)
2. Processing (`processing.html`)
3. Review (`review.html`)
4. Confirmation (`confirmation.html`)
5. Stored Records (`records.html`)

A navigation page is included at `index.html`.

## Scope

- HTML/CSS only
- No backend/API integration
- No OCR logic implemented yet

## Run locally

Open `index.html` directly in browser, or run a local static server:

```bash
python3 -m http.server 8080
```

Then open:

`http://localhost:8080`

## Files

- `index.html` - quick screen navigator
- `upload.html` - upload/camera UI
- `processing.html` - loading state
- `review.html` - editable extracted fields
- `confirmation.html` - submission success
- `records.html` - table view of stored records
- `style.css` - shared wireframe styling
