# PDF Export via Headless Chromium — Design

**Date:** 2026-06-15
**Status:** Approved (pending spec review)
**Author:** Bob Adams (with Claude)

## Problem

The "Export PDF" button (`GET /api/schedule/<week_start>/export-pdf`) builds a PDF
with FPDF in Python. The output does **not** match what the office actually uses: it
has no Ice Line logo, no green title bar, and only roughly approximates the colored
rows. The good-looking PDF the office prints is produced manually via Chrome's
"Save as PDF" at 80% scale, which renders the existing `@media print` CSS.

The two paths have drifted because the layout is maintained in two places (the print
CSS and the FPDF Python code).

## Goal

Make the **Export PDF button a true one-click action** that produces output matching
the manually-generated Chrome PDF — same logo, green title bar, yellow manager /
office-hours rows, green Zak row, In/Out columns — with no manual print dialog and no
manual scale setting.

Reference output: `~/Downloads/6.17.26 to 6.23.26.pdf` (the approved look).

## Approach

Render the **existing page** with **headless Chromium (Playwright)** and print it to
PDF server-side. Because the PDF is produced by the same browser engine rendering the
same DOM and the same `@media print` CSS, it matches the reference exactly and the
**print CSS becomes the single source of truth** — the PDF can no longer drift from
the screen.

The current FPDF generator is **kept as an automatic fallback** for environments where
Chromium is not installed (e.g. local dev on the Mac).

### Why not the alternatives
- **Rebuild FPDF (Option 3):** never pixel-perfect (different font, no gradients) and
  perpetuates two-place maintenance — the root cause of the drift. Kept only as fallback.
- **WeasyPrint (Option 2):** lighter, but no JS means a duplicated server-rendered HTML
  template, and CSS3 gaps make an exact match unlikely.

## Components

### 1. Print mode in the front-end (`static/js/main.js`, `templates/index.html`)
- Recognize URL params `?print=1&week=YYYY-MM-DD`.
- In print mode: load the requested week, suppress interactive chrome (toolbar, legend,
  coverage, add-employee row — most already handled by `@media print`).
- After the schedule has **fully rendered**, set an explicit readiness signal:
  `window.__printReady = true` and `document.body.dataset.printReady = "1"`.
  This gives Chromium a deterministic "safe to print" condition instead of a guessed
  timeout. The signal must be set only after the async schedule fetch + DOM render
  complete.

### 2. Rewritten endpoint `GET /api/schedule/<week_start>/export-pdf` (`app.py`)
- Try the Chromium path:
  1. Launch headless Chromium via Playwright **sync API**.
  2. `goto("http://127.0.0.1:5001/?print=1&week=<week_start>")`.
  3. `page.wait_for_function("window.__printReady === true")` (bounded timeout, e.g. 10s).
  4. **Auto-fit scale:** emulate print media, measure rendered content
     (`scrollWidth`/`scrollHeight` of the schedule container), and compute the largest
     `scale` in `[0.1, 1.0]` that fits one landscape A4 printable area (297×210 mm minus
     margins). Clamp so it never enlarges past 1.0.
  5. `page.pdf(landscape=True, format="A4", scale=<computed>, print_background=True,
     margin=<small uniform>)`.
- On **any** failure (Playwright import error, Chromium missing, navigation/timeout),
  log a warning and fall back to the existing FPDF generator.
- Refactor the current inline FPDF code into a helper `_export_pdf_fpdf(data)` returning
  PDF bytes, so both the fallback and the (unchanged) filename/streaming logic reuse it.
- Filename scheme unchanged: `schedule_<d1>-<yy>_to_<d2>-<yy>.pdf`.

### 3. Concurrency (`app.py` run block)
- Chromium fetches the page from our own server while the export request is open, so the
  server must handle a concurrent request.
- **Prod:** gunicorn already runs `--workers 9` → fine, no change.
- **Dev:** change `app.run(host='0.0.0.0', port=5001, debug=Config.DEBUG)` to include
  `threaded=True` so the single dev process can serve the self-request.

### 4. Configuration
- The base URL/port for the self-request defaults to `http://127.0.0.1:5001` and is
  overridable via an env var (e.g. `PDF_RENDER_BASE_URL`) read through `Config`, in case
  the bind address/port changes in deployment.

### 5. Dependencies & deployment
- Add `playwright` to `requirements.txt`.
- `DEPLOYMENT.md`: document one-time `playwright install chromium` and
  `playwright install-deps chromium` (system libs) on the LXC; note the ~150–300 MB
  footprint and that absence triggers the FPDF fallback (so deploy won't break).

## Data Flow

```
Browser: click "Export PDF"
  -> GET /api/schedule/<week>/export-pdf
       -> [Chromium path]
            launch headless chromium
            goto http://127.0.0.1:5001/?print=1&week=<week>   --- served by another gunicorn worker
              -> main.js renders schedule, sets window.__printReady
            wait_for __printReady
            measure content -> compute auto-fit scale
            page.pdf(landscape, A4, scale)  -> PDF bytes
       -> [on failure] _export_pdf_fpdf(build_schedule_response(week)) -> PDF bytes
  -> send_file(pdf, download_name="schedule_...pdf")
```

## Error Handling
- Chromium path wrapped in try/except; failures log a warning and fall through to FPDF.
- `wait_for_function` bounded by timeout so a stuck render can't hang the worker.
- Browser/context always closed in a `finally` (no leaked Chromium processes).
- Endpoint preserves the existing outer try/except returning `400` with a JSON error if
  even the fallback fails.

## Testing
- **Manual / primary:** with Chromium installed, export a known week and diff visually
  against `6.17.26 to 6.23.26.pdf` (logo, green bar, yellow/green rows, In/Out, auto-fit
  on one landscape page).
- **Fallback:** simulate missing Chromium (uninstall / force import error) and confirm
  the button still returns a valid FPDF PDF and logs the fallback.
- **Auto-fit:** export a week with the full roster and a near-empty week; both fit one
  landscape page without overflow or excessive shrinkage.
- **Concurrency:** confirm export works on the dev server with `threaded=True` (self-
  request doesn't deadlock).

## Out of Scope
- Auth (the app has none today; the self-request is unauthenticated localhost).
- Browser-process pooling/reuse (launch-per-request is acceptable at this volume; can be
  optimized later if latency matters).
- Changing the Excel export or the time-off calendar PDFs.
```
