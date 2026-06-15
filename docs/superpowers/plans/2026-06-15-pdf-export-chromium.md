# Chromium PDF Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Export PDF" button render the existing schedule page with headless Chromium so the downloaded PDF matches the manually-produced Chrome PDF exactly, auto-fit to one landscape page, with the current FPDF generator kept as an automatic fallback.

**Architecture:** The front-end gains a `?print=1&week=...` mode that renders the schedule and raises a `window.__printReady` flag. The `export-pdf` endpoint launches Playwright Chromium, navigates to that URL on `127.0.0.1:5001`, waits for the flag, measures the content to compute an auto-fit scale, and prints to PDF. Any Chromium failure falls back to the existing FPDF code (refactored into a helper). The dev server is switched to `threaded=True` so the self-request doesn't deadlock.

**Tech Stack:** Flask, Playwright (sync API) + Chromium, fpdf2 (fallback), vanilla JS front-end.

**Spec:** `docs/superpowers/specs/2026-06-15-pdf-export-chromium-design.md`

**Verification note:** This project has no automated test suite and the core deliverable is browser-rendering fidelity, which is verified by inspecting real output. Each task's verification runs real commands (curl/python) and, where relevant, a visual diff against the reference PDF `~/Downloads/6.17.26 to 6.23.26.pdf`. Run the app locally with `python app.py` (port 5001) for verification steps.

---

## Task 1: Front-end print mode + readiness flag

**Files:**
- Modify: `static/js/main.js:93-112` (the `DOMContentLoaded` handler)

- [ ] **Step 1: Add print-mode handling to the init handler**

Replace the existing `DOMContentLoaded` handler body (lines 93-112) with the version below. It reads `?print=1&week=YYYY-MM-DD` from the URL, uses the supplied week instead of the server's current week when present, skips interactive setup in print mode, and sets `window.__printReady` only after the schedule has rendered.

```javascript
document.addEventListener('DOMContentLoaded', async function() {
    loadDarkModePreference();

    const params = new URLSearchParams(window.location.search);
    const isPrintMode = params.get('print') === '1';
    const weekParam = params.get('week');

    if (weekParam) {
        State.currentWeekStart = weekParam;
    } else {
        try {
            const response = await fetch(`${Config.API_BASE}/api/current-week`);
            const data = await response.json();
            State.currentWeekStart = data.weekStart;
            console.log('Current week from server:', data);
        } catch (error) {
            console.error('Failed to get current week:', error);
            State.currentWeekStart = getWeekStartFallback(new Date());
        }
    }

    await loadSchedule(State.currentWeekStart);
    renderSchedule();

    if (isPrintMode) {
        // Signal to headless Chromium that the schedule is fully rendered.
        document.body.classList.add('print-mode');
        document.body.dataset.printReady = '1';
        window.__printReady = true;
        console.log('Print mode ready for week', State.currentWeekStart);
        return; // Skip interactive listeners/shortcuts when generating a PDF.
    }

    setupEventListeners();
    setupKeyboardShortcuts();

    console.log('Schedule loaded:', scheduleData);
});
```

- [ ] **Step 2: Verify normal mode still loads**

Run: `python app.py` (in one terminal), then in another:
`curl -s http://127.0.0.1:5001/ | grep -c "main.js"`
Expected: `1` (page still served). Open `http://127.0.0.1:5001/` in a browser — schedule loads and is interactive as before.

- [ ] **Step 3: Verify print mode renders and flags ready**

In a browser open `http://127.0.0.1:5001/?print=1&week=2026-06-17` (use a week that exists in the DB; pick any week visible in the app). Open devtools console and run `window.__printReady` → expect `true`. Confirm the toolbar is hidden (via existing `@media print` styles it is hidden in print preview; on screen the `.print-mode` class is cosmetic only and the table is visible).

- [ ] **Step 4: Commit**

```bash
git add static/js/main.js
git commit -m "Add ?print mode and readiness flag to schedule front-end"
```

---

## Task 2: Refactor the FPDF generator into a reusable helper

**Files:**
- Modify: `app.py:959-1104` (the `export_schedule_pdf` route)

This extracts the existing FPDF body into a standalone function returning `(pdf_bytes, filename)` so it can serve as the Chromium fallback. **Behavior is unchanged** — this is a pure refactor.

- [ ] **Step 1: Extract the FPDF logic into a module-level helper**

Add this function near the other module-level helpers in `app.py` (e.g. just above the `create_app`/route definitions, alongside `parse_time_to_minutes`). Move the body of the current `export_schedule_pdf` into it, replacing `data = build_schedule_response(week_start)` with a `data` parameter and returning bytes + filename instead of calling `send_file`.

```python
def build_schedule_pdf_fpdf(data):
    """Render a schedule PDF with FPDF. Returns (pdf_bytes, filename).

    Fallback generator used when headless Chromium is unavailable.
    """
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=10)

    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, f"Ice Line Office Schedule - Week of {data['weekTitle']}", ln=True, align='C')
    pdf.ln(3)

    name_col_w = 50
    day_col_w = 26
    sub_col_w = 13
    hours_col_w = 16
    row_h = 7

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(217, 217, 217)
    pdf.cell(name_col_w, row_h, 'Employee', 1, 0, 'C', True)
    for day in data['days']:
        pdf.cell(day_col_w, row_h, f"{day['name']} {day['date']}", 1, 0, 'C', True)
    pdf.cell(hours_col_w, row_h, 'Hours', 1, 1, 'C', True)

    pdf.set_font('Helvetica', 'B', 7)
    pdf.cell(name_col_w, row_h, '', 1, 0, 'C', True)
    for _ in data['days']:
        pdf.cell(sub_col_w, row_h, 'In', 1, 0, 'C', True)
        pdf.cell(sub_col_w, row_h, 'Out', 1, 0, 'C', True)
    pdf.cell(hours_col_w, row_h, '', 1, 1, 'C', True)

    def write_employee_row(emp, fill_rgb=None):
        pdf.set_font('Helvetica', 'B' if fill_rgb else '', 8)
        if fill_rgb:
            pdf.set_fill_color(*fill_rgb)

        name = emp['name']
        if emp.get('phone'):
            name += f"  {emp['phone']}"
        pdf.cell(name_col_w, row_h, name, 1, 0, 'L', bool(fill_rgb))

        pdf.set_font('Helvetica', '', 8)
        for shift in emp['shifts']:
            in_val = shift['in'] if shift and shift.get('in') else ''
            out_val = shift['out'] if shift and shift.get('out') else ''
            pdf.cell(sub_col_w, row_h, str(in_val), 1, 0, 'C', bool(fill_rgb))
            pdf.cell(sub_col_w, row_h, str(out_val), 1, 0, 'C', bool(fill_rgb))

        total = 0
        for shift in emp['shifts']:
            if shift and shift.get('in') and shift.get('out'):
                if shift['in'] == '-' or shift['out'] == '-':
                    continue
                in_mins = parse_time_to_minutes(shift['in'])
                out_mins = parse_time_to_minutes(shift['out'])
                if shift['out'] == 'CLOSE':
                    out_mins = parse_time_to_minutes('10:00 PM')
                if in_mins is not None and out_mins is not None and out_mins > in_mins:
                    total += (out_mins - in_mins) / 60

        hours_str = f"{total:.1f}" if total > 0 else '-'
        pdf.set_font('Helvetica', 'B' if total > 40 else '', 8)
        if total > 40:
            pdf.set_text_color(255, 0, 0)
        pdf.cell(hours_col_w, row_h, hours_str, 1, 1, 'C', bool(fill_rgb))
        pdf.set_text_color(0, 0, 0)

    for emp in data['managers']:
        write_employee_row(emp, (255, 255, 0))
    pdf.ln(2)

    if data['zakReilly']:
        write_employee_row(data['zakReilly'], (146, 208, 80))
    pdf.ln(2)

    for emp in data['employees']:
        write_employee_row(emp)
    pdf.ln(2)

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(255, 255, 0)
    pdf.cell(name_col_w, row_h, 'Front Office Hours*', 1, 0, 'L', True)
    pdf.set_font('Helvetica', '', 8)
    for oh in data['officeHours']:
        in_val = oh.get('in', '') or ''
        out_val = oh.get('out', '') or ''
        if in_val == 'CLOSED':
            pdf.cell(day_col_w, row_h, 'CLOSED', 1, 0, 'C', True)
        else:
            pdf.cell(sub_col_w, row_h, str(in_val), 1, 0, 'C', True)
            pdf.cell(sub_col_w, row_h, str(out_val), 1, 0, 'C', True)
    pdf.cell(hours_col_w, row_h, '', 1, 1, 'C', True)

    pdf.set_font('Helvetica', '', 7)
    pdf.cell(name_col_w, row_h, '* Hours are subject to change', 0, 0, 'L')
    pdf.set_font('Helvetica', 'B', 7)
    pdf.set_text_color(255, 0, 0)
    pdf.cell(0, row_h, 'IF UNABLE TO WORK A SCHEDULED SHIFT YOU MUST FIND A REPLACEMENT', 0, 1, 'C')
    pdf.set_text_color(0, 0, 0)

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(255, 255, 0)
    pdf.cell(name_col_w, row_h, 'Special Events:', 1, 0, 'L', True)
    pdf.set_font('Helvetica', '', 8)
    for events in data['events']:
        event_text = ', '.join(events) if events else ''
        pdf.cell(day_col_w, row_h, event_text, 1, 0, 'C', False)
    pdf.cell(hours_col_w, row_h, '', 1, 1, 'C', False)

    d1 = data['days'][0]['date'].replace('/', '-')
    d2 = data['days'][6]['date'].replace('/', '-')
    year = data['weekTitle'].split(', ')[-1][-2:]
    filename = f"schedule_{d1}-{year}_to_{d2}-{year}.pdf"

    output = BytesIO()
    pdf.output(output)
    output.seek(0)
    return output.read(), filename
```

- [ ] **Step 2: Point the route at the helper (temporary, replaced in Task 3)**

Replace the body of `export_schedule_pdf` (lines 960-1104) with a thin version that calls the helper, so the refactor is verifiable on its own:

```python
    @app.route('/api/schedule/<week_start>/export-pdf', methods=['GET'])
    def export_schedule_pdf(week_start):
        """Export schedule to PDF (FPDF fallback path; Chromium added in Task 3)."""
        try:
            data = build_schedule_response(week_start)
            pdf_bytes, filename = build_schedule_pdf_fpdf(data)
            return send_file(
                BytesIO(pdf_bytes),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename,
            )
        except Exception as e:
            logging.error(f"Error exporting PDF: {e}")
            return jsonify({'error': str(e)}), 400
```

- [ ] **Step 3: Verify the export still works and is a valid PDF**

Run `python app.py`, then:
`curl -s -o /tmp/sched.pdf "http://127.0.0.1:5001/api/schedule/2026-06-17/export-pdf" && file /tmp/sched.pdf`
Expected: `/tmp/sched.pdf: PDF document, version 1.x ...` (non-zero size). Open it — it should look identical to the pre-refactor FPDF output.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Refactor FPDF schedule export into reusable helper"
```

---

## Task 3: Chromium rendering path with auto-fit + fallback

**Files:**
- Modify: `app.py:28-33` (Config — add render base URL)
- Modify: `app.py` (the `export_schedule_pdf` route from Task 2)

- [ ] **Step 1: Add the render base URL to Config**

In `class Config` (after line 33, `BACKUP_IMPORT_ENABLED`), add:

```python
    PDF_RENDER_BASE_URL = os.environ.get('PDF_RENDER_BASE_URL', 'http://127.0.0.1:5001')
    PDF_RENDER_TIMEOUT_MS = int(os.environ.get('PDF_RENDER_TIMEOUT_MS', '10000'))
```

- [ ] **Step 2: Add the Chromium renderer helper**

Add this module-level function near `build_schedule_pdf_fpdf`. It launches Chromium, waits for `window.__printReady`, measures the rendered content, computes an auto-fit scale for one landscape A4 page, and returns PDF bytes. It raises on any failure so the caller can fall back.

```python
def build_schedule_pdf_chromium(week_start, base_url, timeout_ms):
    """Render the live schedule page to PDF with headless Chromium.

    Returns PDF bytes. Raises on any failure (caller falls back to FPDF).
    """
    from playwright.sync_api import sync_playwright

    # A4 landscape printable area in inches (8.27 x 11.69 in), minus 0.25in margins.
    margin_in = 0.25
    page_w_in = 11.69 - 2 * margin_in
    page_h_in = 8.27 - 2 * margin_in
    url = f"{base_url}/?print=1&week={week_start}"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.emulate_media(media='print')
            page.goto(url, wait_until='networkidle', timeout=timeout_ms)
            page.wait_for_function('window.__printReady === true', timeout=timeout_ms)

            # Measure full rendered content at scale 1 (CSS px @ 96dpi).
            metrics = page.evaluate(
                "() => ({ w: document.documentElement.scrollWidth,"
                " h: document.documentElement.scrollHeight })"
            )
            content_w_in = metrics['w'] / 96.0
            content_h_in = metrics['h'] / 96.0

            scale = min(page_w_in / content_w_in, page_h_in / content_h_in, 1.0)
            scale = max(scale, 0.1)  # Playwright clamps to [0.1, 2.0].

            pdf_bytes = page.pdf(
                format='A4',
                landscape=True,
                scale=scale,
                print_background=True,
                margin={
                    'top': f'{margin_in}in', 'bottom': f'{margin_in}in',
                    'left': f'{margin_in}in', 'right': f'{margin_in}in',
                },
            )
            return pdf_bytes
        finally:
            browser.close()
```

- [ ] **Step 3: Wire the route to try Chromium then fall back to FPDF**

Replace the `export_schedule_pdf` route body from Task 2 with:

```python
    @app.route('/api/schedule/<week_start>/export-pdf', methods=['GET'])
    def export_schedule_pdf(week_start):
        """Export schedule to PDF. Prefers headless Chromium (pixel-matches the
        on-screen print view); falls back to the FPDF generator if Chromium is
        unavailable or errors."""
        try:
            data = build_schedule_response(week_start)
            _, filename = build_schedule_pdf_fpdf(data)  # filename only; cheap.

            pdf_bytes = None
            try:
                pdf_bytes = build_schedule_pdf_chromium(
                    week_start,
                    Config.PDF_RENDER_BASE_URL,
                    Config.PDF_RENDER_TIMEOUT_MS,
                )
            except Exception as e:
                logging.warning(f"Chromium PDF render failed, using FPDF fallback: {e}")
                pdf_bytes, filename = build_schedule_pdf_fpdf(data)

            return send_file(
                BytesIO(pdf_bytes),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename,
            )
        except Exception as e:
            logging.error(f"Error exporting PDF: {e}")
            return jsonify({'error': str(e)}), 400
```

Note: computing `filename` via `build_schedule_pdf_fpdf` also renders a throwaway PDF. To avoid that waste, extract the filename logic into a tiny helper and call it from both. Add near the helpers:

```python
def schedule_pdf_filename(data):
    """Build the download filename for a schedule PDF: schedule_<d1>-<yy>_to_<d2>-<yy>.pdf"""
    d1 = data['days'][0]['date'].replace('/', '-')
    d2 = data['days'][6]['date'].replace('/', '-')
    year = data['weekTitle'].split(', ')[-1][-2:]
    return f"schedule_{d1}-{year}_to_{d2}-{year}.pdf"
```

Then in `build_schedule_pdf_fpdf`, replace its inline filename block with `filename = schedule_pdf_filename(data)`, and in the route replace `_, filename = build_schedule_pdf_fpdf(data)` with `filename = schedule_pdf_filename(data)`.

- [ ] **Step 4: Install Playwright + Chromium locally for verification**

Run:
```bash
pip install playwright
playwright install chromium
```
Expected: Chromium downloads successfully.

- [ ] **Step 5: Verify the Chromium path produces the branded PDF**

Run `python app.py` (requires Task 4's `threaded=True` for the self-request — do Task 4 first if the request hangs). Then:
`curl -s -o /tmp/sched_chromium.pdf "http://127.0.0.1:5001/api/schedule/2026-06-17/export-pdf" && file /tmp/sched_chromium.pdf`
Expected: a valid PDF. Open it and confirm it matches `~/Downloads/6.17.26 to 6.23.26.pdf`: Ice Line logo, green title bar, yellow manager/office-hours rows, green Zak row, In/Out columns, all on **one** landscape page.

- [ ] **Step 6: Verify the fallback path**

Temporarily force a failure by setting a bad base URL:
`PDF_RENDER_BASE_URL=http://127.0.0.1:9 python app.py`
Then `curl -s -o /tmp/sched_fb.pdf "http://127.0.0.1:5001/api/schedule/2026-06-17/export-pdf" && file /tmp/sched_fb.pdf`
Expected: valid PDF (the plain FPDF version), and the server log shows `Chromium PDF render failed, using FPDF fallback`.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "Render Export PDF via headless Chromium with auto-fit and FPDF fallback"
```

---

## Task 4: Dev-server concurrency

**Files:**
- Modify: `app.py:1448` (the `app.run` call)

- [ ] **Step 1: Enable threading on the dev server**

Replace line 1448:

```python
    app.run(host='0.0.0.0', port=5001, debug=Config.DEBUG, threaded=True)
```

`threaded=True` lets the single dev process serve Chromium's page request while the export request is open. Prod (gunicorn `--workers 9`) already handles this.

- [ ] **Step 2: Verify no self-request deadlock**

Run `python app.py`, then:
`time curl -s -o /tmp/sched.pdf "http://127.0.0.1:5001/api/schedule/2026-06-17/export-pdf" && file /tmp/sched.pdf`
Expected: completes in a few seconds (not hanging until timeout) and produces the Chromium-rendered PDF.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "Run dev server threaded so PDF self-request doesn't deadlock"
```

---

## Task 5: Dependencies + deployment docs

**Files:**
- Modify: `requirements.txt`
- Modify: `DEPLOYMENT.md`

- [ ] **Step 1: Add Playwright to requirements**

Add to `requirements.txt` under the existing deps:

```
playwright>=1.40.0  # Headless Chromium for branded PDF export (FPDF fallback if absent)
```

- [ ] **Step 2: Document Chromium install in DEPLOYMENT.md**

Add a subsection (near the dependency/install steps) explaining the one-time browser install on the LXC:

```markdown
### PDF export (headless Chromium)

The "Export PDF" button renders the schedule page with headless Chromium so the
PDF matches the on-screen print view. After `pip install -r requirements.txt`,
install the browser and its system libraries once:

    source venv/bin/activate
    playwright install chromium
    playwright install-deps chromium   # apt system libraries (run as root if needed)

Footprint is ~150-300 MB. If Chromium is missing or fails, the endpoint
automatically falls back to the plain FPDF generator, so a missing browser will
not break the button — it just produces the unbranded layout.

The page is fetched from `PDF_RENDER_BASE_URL` (default `http://127.0.0.1:5001`).
Override it if the service binds to a different host/port.
```

- [ ] **Step 3: Verify requirements install cleanly**

Run: `pip install -r requirements.txt`
Expected: no errors; `playwright` resolves.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt DEPLOYMENT.md
git commit -m "Add Playwright dependency and document Chromium install for PDF export"
```

---

## Final verification

- [ ] With Chromium installed and `python app.py` running, click "Export PDF" in the browser UI for a populated week. Confirm the downloaded file visually matches `~/Downloads/6.17.26 to 6.23.26.pdf` on one landscape page.
- [ ] Export a near-empty week and the full-roster week; both fit one page without overflow (auto-fit working).
- [ ] Confirm normal interactive use of the app is unchanged (toolbar, editing, navigation).
```
