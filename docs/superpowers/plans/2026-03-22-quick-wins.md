# Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three quick wins — cell editing focus loss, real PDF export, and SECRET_KEY in .env

**Architecture:** Three independent fixes. Cell editing fix is JS-only (stop full DOM re-render on input change). PDF export adds a server-side endpoint using fpdf2. SECRET_KEY uses python-dotenv to load .env.

**Tech Stack:** Flask, fpdf2, python-dotenv, vanilla JavaScript

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `static/js/main.js` | Fix handleShiftInput to not re-render; update exportToPDF to hit server |
| Modify | `app.py` | Add dotenv loading, add PDF export route |
| Modify | `requirements.txt` | Add fpdf2, python-dotenv |
| Create | `.env` | SECRET_KEY value |
| Create | `.env.example` | Template showing required vars |

---

## Chunk 1: Cell Editing Fix + .env Setup

### Task 1: Fix handleShiftInput focus loss

**Files:**
- Modify: `static/js/main.js:823-851`

The bug: `handleShiftInput` calls `renderSchedule()` + `setupEventListeners()` which rebuilds the entire DOM, killing focus on whatever cell the user just tabbed to.

The fix: Replace the re-render with an in-place update of just the hours cell for that employee row.

- [ ] **Step 1: Modify handleShiftInput to update hours in-place**

Replace the function at line 823 with:

```javascript
function handleShiftInput(input, section, empIndex, dayIndex, type) {
    saveStateForUndo();

    const value = parseTimeInput(input.value);

    let employee;
    if (section === 'manager') {
        employee = scheduleData.managers[empIndex];
    } else if (section === 'zak') {
        employee = scheduleData.zakReilly;
    } else {
        employee = scheduleData.employees[empIndex];
    }

    if (!employee.shifts[dayIndex]) {
        employee.shifts[dayIndex] = { in: null, out: null };
    }

    employee.shifts[dayIndex][type] = value;

    if (!employee.shifts[dayIndex].in && !employee.shifts[dayIndex].out) {
        employee.shifts[dayIndex] = null;
    }

    input.value = value || '';

    // Update hours cell in-place instead of full re-render
    const row = input.closest('tr');
    if (row) {
        const hoursCell = row.querySelector('.hours-cell');
        if (hoursCell) {
            const totalHours = calculateWeeklyHours(employee.shifts);
            const isOvertime = totalHours > Config.OVERTIME_THRESHOLD;
            hoursCell.className = 'hours-cell' + (isOvertime ? ' overtime' : '');
            hoursCell.title = isOvertime ? `⚠️ Over ${Config.OVERTIME_THRESHOLD} hours!` : '';
            hoursCell.textContent = totalHours > 0 ? totalHours.toFixed(1) : '-';
        }
    }

    markUnsaved();
}
```

Key change: Removed `renderSchedule()` and `setupEventListeners()`. Instead finds the hours cell in the same row and updates it directly.

- [ ] **Step 2: Test manually**

Run: `cd /Users/badams/Projects/iceline/employee-scheduler && python app.py`

Open http://localhost:5001, type in a cell, Tab to next cell — focus should stay. Type "9" in an In cell, Tab to Out cell, type "5" — both should stick without losing focus.

- [ ] **Step 3: Commit**

```bash
git add static/js/main.js
git commit -m "fix: stop full DOM re-render on shift input change

Removes renderSchedule()+setupEventListeners() from handleShiftInput.
Updates only the hours cell in-place, preserving focus when tabbing."
```

### Task 2: Move SECRET_KEY to .env

**Files:**
- Create: `.env`
- Create: `.env.example`
- Modify: `app.py:1-15` (add dotenv import/load)
- Modify: `requirements.txt`

- [ ] **Step 1: Add python-dotenv to requirements.txt**

Append `python-dotenv>=1.0.0` to `requirements.txt`.

- [ ] **Step 2: Create .env.example**

```
# Ice Line Employee Scheduler - Environment Variables
# Copy this file to .env and fill in values

SECRET_KEY=change-me-to-a-random-string
# DATABASE_PATH=schedule.db
# FLASK_DEBUG=false
```

- [ ] **Step 3: Create .env with generated key**

```
SECRET_KEY=<generate a 48-char random hex string using python -c "import secrets; print(secrets.token_hex(24))">
```

- [ ] **Step 4: Verify .env is in .gitignore**

Already present at line 33 of `.gitignore`. No change needed.

- [ ] **Step 5: Add load_dotenv() to app.py**

At the top of `app.py`, after existing imports (line 17), add:

```python
from dotenv import load_dotenv
load_dotenv()
```

The `Config` class already reads `os.environ.get('SECRET_KEY', ...)` so it will pick up the value automatically.

- [ ] **Step 6: Install and test**

Run:
```bash
cd /Users/badams/Projects/iceline/employee-scheduler
pip install python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('KEY:', os.environ.get('SECRET_KEY', 'NOT SET')[:8] + '...')"
```

Expected: prints first 8 chars of your key, not "dev-secret-key".

- [ ] **Step 7: Commit**

```bash
git add app.py requirements.txt .env.example
git commit -m "feat: load SECRET_KEY from .env via python-dotenv

Adds python-dotenv, .env.example template. Config class already reads
os.environ so no other changes needed."
```

**IMPORTANT:** Do NOT `git add .env` — it contains the actual secret.

---

## Chunk 2: Server-Side PDF Export

### Task 3: Add PDF export endpoint

**Files:**
- Modify: `requirements.txt` (add fpdf2)
- Modify: `app.py:690` (add new route before the Excel export route)
- Modify: `static/js/main.js:655-666` (update exportToPDF function)

- [ ] **Step 1: Add fpdf2 to requirements.txt**

Append `fpdf2>=2.7.0` to `requirements.txt`.

- [ ] **Step 2: Install fpdf2**

Run: `pip install fpdf2`

- [ ] **Step 3: Add PDF export route in app.py**

After the Excel export route (after line 835), add the PDF export route. Add `from fpdf import FPDF` at the top of `app.py` with the other imports.

Import addition (line 17 area):
```python
from fpdf import FPDF
```

New route:
```python
@app.route('/api/schedule/<week_start>/export-pdf', methods=['GET'])
def export_schedule_pdf(week_start):
    """Export schedule to PDF with formatting"""
    try:
        data = build_schedule_response(week_start)

        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=10)

        # Title
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 10, f"Ice Line Office Schedule - Week of {data['weekTitle']}", ln=True, align='C')
        pdf.ln(3)

        # Table configuration
        name_col_w = 50
        day_col_w = 26  # Each day gets 2 sub-columns (In/Out) of 13mm each
        sub_col_w = 13
        hours_col_w = 16
        row_h = 7

        # Day header row
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_fill_color(217, 217, 217)  # Gray
        pdf.cell(name_col_w, row_h, 'Employee', 1, 0, 'C', True)
        for day in data['days']:
            pdf.cell(day_col_w, row_h, f"{day['name']} {day['date']}", 1, 0, 'C', True)
        pdf.cell(hours_col_w, row_h, 'Hours', 1, 1, 'C', True)

        # In/Out sub-header
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

            # Calculate hours
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

        # Managers (yellow)
        for emp in data['managers']:
            write_employee_row(emp, (255, 255, 0))

        # Blank separator row
        pdf.ln(2)

        # Zak (green)
        if data['zakReilly']:
            write_employee_row(data['zakReilly'], (146, 208, 80))

        # Blank separator
        pdf.ln(2)

        # Staff (no fill)
        for emp in data['employees']:
            write_employee_row(emp)

        pdf.ln(2)

        # Office Hours row
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

        # Notice
        pdf.set_font('Helvetica', '', 7)
        pdf.cell(name_col_w, row_h, '* Hours are subject to change', 0, 0, 'L')
        pdf.set_font('Helvetica', 'B', 7)
        pdf.set_text_color(255, 0, 0)
        pdf.cell(0, row_h, 'IF UNABLE TO WORK A SCHEDULED SHIFT YOU MUST FIND A REPLACEMENT', 0, 1, 'C')
        pdf.set_text_color(0, 0, 0)

        # Events row
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_fill_color(255, 255, 0)
        pdf.cell(name_col_w, row_h, 'Special Events:', 1, 0, 'L', True)
        pdf.set_font('Helvetica', '', 8)
        for events in data['events']:
            event_text = ', '.join(events) if events else ''
            pdf.cell(day_col_w, row_h, event_text, 1, 0, 'C', False)
        pdf.cell(hours_col_w, row_h, '', 1, 1, 'C', False)

        # Generate filename
        d1 = data['days'][0]['date'].replace('/', '-')
        d2 = data['days'][6]['date'].replace('/', '-')
        year = data['weekTitle'].split(', ')[-1][-2:]
        filename = f"schedule_{d1}-{year}_to_{d2}-{year}.pdf"

        output = BytesIO()
        pdf.output(output)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logging.error(f"Error exporting PDF: {e}")
        return jsonify({'error': str(e)}), 400
```

Also add a helper function `parse_time_to_minutes` in app.py (near the helper functions area):

```python
def parse_time_to_minutes(time_str):
    """Convert time string like '9:00 AM' to minutes since midnight"""
    if not time_str or time_str in ('-', 'CLOSE', 'CLOSED'):
        return None
    try:
        time_str = time_str.strip().upper()
        if 'AM' in time_str or 'PM' in time_str:
            parts = time_str.replace('AM', '').replace('PM', '').strip().split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            if 'PM' in time_str and hour != 12:
                hour += 12
            if 'AM' in time_str and hour == 12:
                hour = 0
            return hour * 60 + minute
    except (ValueError, IndexError):
        return None
    return None
```

- [ ] **Step 4: Update exportToPDF in main.js**

Replace the function at line 655:

```javascript
function exportToPDF() {
    window.location.href = `${Config.API_BASE}/api/schedule/${State.currentWeekStart}/export-pdf`;
}
```

- [ ] **Step 5: Install and test**

Run:
```bash
cd /Users/badams/Projects/iceline/employee-scheduler
pip install fpdf2
python app.py
```

Open http://localhost:5001, click the PDF button — should download a real PDF file.

- [ ] **Step 6: Commit**

```bash
git add app.py static/js/main.js requirements.txt
git commit -m "feat: add server-side PDF export using fpdf2

Replaces window.print() with a real PDF download endpoint.
Generates a formatted landscape A4 PDF with colored sections
matching the Excel export layout."
```
