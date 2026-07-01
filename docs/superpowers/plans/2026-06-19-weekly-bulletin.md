# Weekly Bulletin + Notification Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-click, personalized weekly schedule email to all active staff via the Ice Line mail host, with per-recipient delivery logging and a stored snapshot per send, behind an off-by-default safety flag with a test-send-to-self.

**Architecture:** Two new pure modules — `emailer.py` (SMTP send) and `bulletin.py` (render a personalized "your shifts + full week" email from `build_schedule_response` data) — plus two routes (preview + send) and DB tables `publications` (snapshot per send) and `email_outbox` (per-recipient status). Employee `email` is set through the existing employee modals. Everything is additive and gated by `EMAIL_ENABLED`.

**Tech Stack:** Flask, `smtplib.SMTP_SSL` (stdlib — no new dependency), SQLite, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-06-19-weekly-bulletin-design.md`

## Global Constraints

- **Additive only; must not break core scheduling.** No changes to schedule save/version/autosave logic.
- **`EMAIL_ENABLED` defaults to false.** With it off, the send endpoint returns 403; preview still works. Nothing emails staff until the flag is set.
- **No secrets committed.** `SMTP_PASSWORD` only via `.env`; `.env.example` keeps it blank. `.env` is gitignored (verify).
- **SMTP transport (exact):** `smtplib.SMTP_SSL`, host `securemail2.megamailservers.com`, port `465` (implicit SSL), auth user `badams@iceline.info`, From/Reply-To `badams@iceline.info`. NOT Gmail.
- **Recipients:** all `active = 1` employees with a non-empty `email`. Employees without an email → `skipped` outbox row (surfaced in preview).
- **Email is link-free:** no remote images, no URLs, no tracking. Plain text + light inline-styled HTML.
- **No automated test suite** — verify with `./venv/bin/python -c` (real assertions) and `curl`. Do NOT scaffold pytest. Run the app with `./venv/bin/python app.py` (port 5001); back up `schedule.db` before mutating runs.
- **Auth note:** this branch is off `main` (no auth). New endpoints are unauthenticated like the rest of the current app; a follow-up adds `@manager_required` when auth merges. Do not add auth here.
- Commits: clear messages, no `Co-Authored-By` trailers.

---

## Task 1: Config, DB migrations, and `.env.example`

**Files:**
- Modify: `app.py` — `class Config` (after line 35); `init_db` migration block (after line 193).
- Modify: `.env.example`

**Interfaces:**
- Produces: `Config.EMAIL_ENABLED` (bool), `Config.SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/EMAIL_FROM/EMAIL_FROM_NAME/EMAIL_TEST_RECIPIENT`; tables `publications`, `email_outbox`; `employees.email` column.

- [ ] **Step 1: Add email config to `class Config`**

After the `PDF_RENDER_TIMEOUT_MS` line (line 35), add:

```python
    EMAIL_ENABLED = os.environ.get('EMAIL_ENABLED', 'false').lower() == 'true'
    SMTP_HOST = os.environ.get('SMTP_HOST', 'securemail2.megamailservers.com')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '465'))
    SMTP_USER = os.environ.get('SMTP_USER', 'badams@iceline.info')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')  # ONLY from .env
    EMAIL_FROM = os.environ.get('EMAIL_FROM', 'badams@iceline.info')
    EMAIL_FROM_NAME = os.environ.get('EMAIL_FROM_NAME', 'Ice Line Schedule')
    EMAIL_TEST_RECIPIENT = os.environ.get('EMAIL_TEST_RECIPIENT', 'badams@iceline.info')
```

- [ ] **Step 2: Add migrations in `init_db`**

After the `schedules.version` migration block (ends ~line 193), add:

```python
    # Notification foundation (weekly bulletin) — additive, idempotent
    cursor.execute("PRAGMA table_info(employees)")
    employee_cols = {row[1] for row in cursor.fetchall()}
    if 'email' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN email TEXT")
        logging.info("Migrated: added employees.email column")

    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start DATE NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'bulletin',
            snapshot_json TEXT NOT NULL,
            recipient_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            is_test INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS email_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id INTEGER,
            message_type TEXT NOT NULL,
            employee_id INTEGER,
            recipient_email TEXT NOT NULL,
            recipient_name TEXT,
            subject TEXT,
            status TEXT NOT NULL,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE SET NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_publication ON email_outbox(publication_id);
    ''')
```

- [ ] **Step 3: Add keys to `.env.example`**

Append to `.env.example`:

```
# Email / weekly bulletin (SMTP via megamailservers)
EMAIL_ENABLED=false
SMTP_HOST=securemail2.megamailservers.com
SMTP_PORT=465
SMTP_USER=badams@iceline.info
SMTP_PASSWORD=
EMAIL_FROM=badams@iceline.info
EMAIL_FROM_NAME=Ice Line Schedule
EMAIL_TEST_RECIPIENT=badams@iceline.info
```

- [ ] **Step 4: Verify migration + config**

```bash
cp schedule.db /tmp/schedule.db.bak
./venv/bin/python -c "import ast; ast.parse(open('app.py').read()); print('syntax OK')"
./venv/bin/python -c "
import app, sqlite3
c = sqlite3.connect('schedule.db')
cols = {r[1] for r in c.execute('PRAGMA table_info(employees)')}
assert 'email' in cols, 'email col missing'
tbls = {r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")}
assert {'publications','email_outbox'} <= tbls, f'missing tables: {tbls}'
assert app.Config.EMAIL_ENABLED is False
assert app.Config.SMTP_PORT == 465
print('migration + config OK')
"
```
Expected: `syntax OK`, `migration + config OK`.

- [ ] **Step 5: Commit**

```bash
git add app.py .env.example
git commit -m "Bulletin: add email config, employees.email, publications + email_outbox tables"
```

---

## Task 2: `emailer.py` — SMTP send

**Files:**
- Create: `emailer.py`

**Interfaces:**
- Produces:
  - `build_message(from_addr, from_name, to_addr, subject, html_body, text_body) -> email.message.EmailMessage` (pure, testable).
  - `send_email(smtp, to_addr, subject, html_body, text_body)` where `smtp` is a dict with keys `host, port, user, password, from_addr, from_name`. Sends via `SMTP_SSL`. Raises on failure.

- [ ] **Step 1: Create `emailer.py`**

```python
"""SMTP email sending for the Ice Line scheduler.

Pure of any import from app.py. Transport is implicit-SSL SMTP (megamailservers).
`smtp` is a plain dict so callers pass exactly what they need and this stays testable.
"""
import smtplib
from email.message import EmailMessage
from email.utils import formataddr


def build_message(from_addr, from_name, to_addr, subject, html_body, text_body):
    """Build a multipart/alternative email (text + HTML). Pure — does not send."""
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((from_name, from_addr))
    msg['To'] = to_addr
    msg['Reply-To'] = from_addr
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype='html')
    return msg


def send_email(smtp, to_addr, subject, html_body, text_body):
    """Send one email via implicit-SSL SMTP. Raises on any failure."""
    msg = build_message(
        smtp['from_addr'], smtp['from_name'], to_addr, subject, html_body, text_body
    )
    with smtplib.SMTP_SSL(smtp['host'], smtp['port'], timeout=30) as server:
        server.login(smtp['user'], smtp['password'])
        server.send_message(msg)
```

- [ ] **Step 2: Verify `build_message` (no real send)**

```bash
./venv/bin/python -c "
from emailer import build_message
m = build_message('badams@iceline.info', 'Ice Line Schedule', 'x@example.com',
                  'Test subject', '<p>hi <b>Ava</b></p>', 'hi Ava')
assert m['To'] == 'x@example.com'
assert m['Subject'] == 'Test subject'
assert m['Reply-To'] == 'badams@iceline.info'
assert 'Ice Line Schedule' in m['From'] and 'badams@iceline.info' in m['From']
parts = [p.get_content_type() for p in m.walk()]
assert 'text/plain' in parts and 'text/html' in parts, parts
print('build_message OK:', parts)
"
```
Expected: `build_message OK: [...'text/plain'...'text/html'...]`.

- [ ] **Step 3: Commit**

```bash
git add emailer.py
git commit -m "Bulletin: add emailer module (SMTP_SSL send + testable build_message)"
```

---

## Task 3: `bulletin.py` — render the personalized email

**Files:**
- Create: `bulletin.py`

**Interfaces:**
- Consumes: `schedule_data` shaped like `build_schedule_response(...)` — keys `weekTitle`, `days` (7× `{name,date,...}`), `officeHours` (7× `{in,out}`), `events` (7× list[str]), `managers`/`employees` (list of `{id,name,shifts}`), `zakReilly` (`{...}` or None). Each `shifts` entry is `None` or `{in,out}`.
- Produces: `render_bulletin(employee, schedule_data) -> (subject, html, text)` where `employee` is `{'name': str, 'shifts': [7 items]}`.

- [ ] **Step 1: Create `bulletin.py`**

```python
"""Render the personalized weekly schedule bulletin email.

Pure functions of the schedule_data dict (build_schedule_response shape). Link-free:
no remote images or URLs. Returns (subject, html, text).
"""
import html as _html


def _fmt_shift(shift):
    """A single shift cell -> human string, or None if not working."""
    if not shift:
        return None
    tin, tout = shift.get('in'), shift.get('out')
    if not tin and not tout:
        return None
    if tin in ('-', '') and tout in ('-', ''):
        return None
    return f"{tin or '?'}–{tout or '?'}"  # en-dash between


def _all_people(schedule_data):
    people = list(schedule_data.get('managers', []))
    if schedule_data.get('zakReilly'):
        people.append(schedule_data['zakReilly'])
    people.extend(schedule_data.get('employees', []))
    return people


def _my_shift_lines(employee, days):
    """List of 'Wed 6/24  8:00 AM-4:00 PM' for the employee's working days."""
    lines = []
    for i, day in enumerate(days):
        s = _fmt_shift(employee['shifts'][i]) if i < len(employee['shifts']) else None
        if s:
            lines.append(f"{day['name']} {day['date']}  {s}")
    return lines


def _full_week_text(schedule_data):
    days = schedule_data['days']
    people = _all_people(schedule_data)
    office = schedule_data.get('officeHours', [])
    events = schedule_data.get('events', [])
    out = []
    for i, day in enumerate(days):
        oh = office[i] if i < len(office) else {}
        oh_str = ''
        if oh.get('in') and oh.get('out'):
            oh_str = f"  (office {oh['in']}–{oh['out']})"
        out.append(f"{day['name']} {day['date']}{oh_str}")
        ev = events[i] if i < len(events) else []
        if ev:
            out.append(f"    * {', '.join(ev)}")
        working = []
        for p in people:
            s = _fmt_shift(p['shifts'][i]) if i < len(p['shifts']) else None
            if s:
                working.append(f"{p['name']}: {s}")
        if working:
            for w in working:
                out.append(f"    {w}")
        else:
            out.append("    (no staff scheduled)")
        out.append("")
    return "\n".join(out).rstrip()


def render_bulletin(employee, schedule_data):
    week = schedule_data['weekTitle']
    subject = f"Ice Line schedule — week of {week}"

    mine = _my_shift_lines(employee, schedule_data['days'])
    mine_block = "\n".join(f"  {m}" for m in mine) if mine else "  (no shifts scheduled)"
    full = _full_week_text(schedule_data)

    text = (
        f"Hi {employee['name']} — your shifts for the week of {week}:\n"
        f"{mine_block}\n\n"
        f"{'-' * 40}\nFULL WEEK\n\n{full}\n"
    )

    def esc(s):
        return _html.escape(str(s))

    mine_html = ("<ul>" + "".join(f"<li>{esc(m)}</li>" for m in mine) + "</ul>") if mine \
        else "<p><em>No shifts scheduled.</em></p>"
    full_html = "<pre style=\"font-family:inherit;white-space:pre-wrap;margin:0\">" \
        + esc(full) + "</pre>"
    html = (
        "<div style=\"font-family:system-ui,Arial,sans-serif;max-width:560px;"
        "margin:0 auto;color:#222\">"
        f"<h2 style=\"color:#2d8cf0;margin:0 0 4px\">Ice Line Schedule</h2>"
        f"<p style=\"margin:0 0 12px;color:#666\">Week of {esc(week)}</p>"
        f"<p style=\"margin:0 0 4px\"><strong>Hi {esc(employee['name'])} — "
        f"your shifts:</strong></p>{mine_html}"
        f"<hr style=\"border:none;border-top:1px solid #ddd;margin:16px 0\">"
        f"<p style=\"margin:0 0 6px\"><strong>Full week</strong></p>{full_html}"
        "</div>"
    )
    return subject, html, text
```

- [ ] **Step 2: Verify render (real assertions, no send)**

```bash
./venv/bin/python -c "
from bulletin import render_bulletin
data = {
  'weekTitle': 'June 24th, 2026',
  'days': [{'name':n,'date':d} for n,d in
           [('Wed','6/24'),('Thurs','6/25'),('Fri','6/26'),('Sat','6/27'),
            ('Sun','6/28'),('Mon','6/29'),('Tues','6/30')]],
  'officeHours': [{'in':'8:00 AM','out':'10:00 PM'}]*7,
  'events': [['AAHA Girls'],[],[],[],[],[],[]],
  'managers': [{'id':1,'name':'Bob Adams','shifts':[{'in':'8:00 AM','out':'4:00 PM'}]+[None]*6}],
  'zakReilly': None,
  'employees': [{'id':4,'name':'Ava Hawthorne','shifts':[None,{'in':'1:00 PM','out':'CLOSE'},None,None,None,None,None]}],
}
emp = data['employees'][0]
subject, html, text = render_bulletin(emp, data)
assert 'week of June 24th, 2026' in subject
assert 'Hi Ava Hawthorne' in text and 'Hi Ava Hawthorne' in html
assert '1:00 PM' in text and 'Thurs 6/25' in text          # her shift, personalized
assert 'Bob Adams: 8:00 AM' in text                         # full-week section
assert 'AAHA Girls' in text                                 # events
assert 'http' not in html.lower()                           # link-free
print('render OK'); print(text[:220])
"
```
Expected: `render OK` then the first lines of the rendered text (Ava's Thurs shift on top, full week below).

- [ ] **Step 3: Commit**

```bash
git add bulletin.py
git commit -m "Bulletin: add personalized 'your shifts + full week' renderer"
```

---

## Task 4: Employee email — backend + modals

**Files:**
- Modify: `app.py` — `add_employee` (INSERT), `update_employee` (field loop).
- Modify: `static/js/main.js` — `openAddEmployeeModal`/`saveNewEmployee`, `openEmployeeModal`/`saveEmployee`.

**Interfaces:**
- Produces: `POST /api/employees` and `PUT /api/employees/<id>` accept/persist `email`; employee edit/add modals have an Email field.

- [ ] **Step 1: Persist email in `add_employee`**

In `add_employee`, change the INSERT to include email. Replace:

```python
            cursor.execute(
                '''INSERT INTO employees (name, phone, section, sort_order) 
                   VALUES (?, ?, ?, ?)''',
                (data['name'], data.get('phone', ''), section, next_order)
            )
```
with:
```python
            cursor.execute(
                '''INSERT INTO employees (name, phone, email, section, sort_order)
                   VALUES (?, ?, ?, ?, ?)''',
                (data['name'], data.get('phone', ''), data.get('email', ''), section, next_order)
            )
```

- [ ] **Step 2: Persist email in `update_employee`**

In `update_employee`, add `'email'` to the updatable fields. Replace:

```python
            for field in ['name', 'phone', 'sort_order']:
```
with:
```python
            for field in ['name', 'phone', 'email', 'sort_order']:
```

- [ ] **Step 3: Expose `email` in the schedule payload so the UI can display/preserve it**

In `build_schedule_response`, the inner `build_employee(emp)` returns the per-employee
dict. Add `email` to it (alongside `phone`) so the manager Edit modal can pre-fill the
current value and saving never blanks it out. Change:

```python
            'phone': emp['phone'] or '',
```
to:
```python
            'phone': emp['phone'] or '',
            'email': emp['email'] or '',
```

(This exposes staff email in the schedule API the same way `phone` already is — acceptable
for this internal, LAN-only-until-tunnel tool. When the auth branch's `public_employee()`
sanitizer merges, `email` should stay included since the manager UI needs it; a
finer-grained portal-vs-manager split can come later.)

- [ ] **Step 4: Add Email input to the Add-Employee modal**

In `openAddEmployeeModal`, after the Phone `form-group` block, add:

```javascript
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" id="empEmail" placeholder="name@example.com">
                    </div>
```
And in `saveNewEmployee`, read + send it. Replace:
```javascript
    const phone = document.getElementById('empPhone').value.trim();
```
with:
```javascript
    const phone = document.getElementById('empPhone').value.trim();
    const email = document.getElementById('empEmail').value.trim();
```
and change the POST body `JSON.stringify({ name, phone, section: 'staff' })` to
`JSON.stringify({ name, phone, email, section: 'staff' })`. Also add
`email: newEmp.email || '',` to the `scheduleData.employees.push({ ... })` object so the
newly added in-memory row carries its email.

- [ ] **Step 5: Add Email input to the Edit-Employee modal**

In `openEmployeeModal` (the edit modal HTML), after the Phone `form-group`, add an email field pre-filled from the employee:

```javascript
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" id="empEmail" value="${employee.email || ''}">
                    </div>
```
In `saveEmployee`, read + send it. After the `const phone = ...` line add:
```javascript
    const email = document.getElementById('empEmail').value.trim();
```
change the PUT body `JSON.stringify({ name, phone })` to `JSON.stringify({ name, phone, email })`,
and after `employee.phone = phone;` add `employee.email = email;`.

(With Step 3 including `email` in `build_schedule_response`, the edit modal pre-fills the
current email after any schedule load; the `|| ''` guard covers the transient case.)

- [ ] **Step 6: Verify backend persists email**

```bash
cp schedule.db /tmp/schedule.db.bak
./venv/bin/python app.py >/tmp/t4.log 2>&1 &
sleep 3
EID=$(curl -s http://127.0.0.1:5001/api/employees | ./venv/bin/python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -s -o /dev/null -w "put=%{http_code}\n" -X PUT -H 'Content-Type: application/json' -d '{"email":"test@example.com"}' http://127.0.0.1:5001/api/employees/$EID
curl -s http://127.0.0.1:5001/api/employees | ./venv/bin/python -c "import sys,json;e=[x for x in json.load(sys.stdin) if x['id']==$EID][0];print('email now:', e.get('email')); assert e.get('email')=='test@example.com'"
kill %1 2>/dev/null
node --check static/js/main.js && echo "main.js OK"
```
Expected: `put=200`, `email now: test@example.com`, `main.js OK`. Also confirm the
schedule payload now carries email:
```bash
./venv/bin/python app.py >/tmp/t4b.log 2>&1 & sleep 3
WEEK=$(curl -s http://127.0.0.1:5001/api/current-week | ./venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['weekStart'])")
curl -s http://127.0.0.1:5001/api/schedule/$WEEK | ./venv/bin/python -c "import sys,json;d=json.load(sys.stdin);ppl=d['managers']+([d['zakReilly']] if d['zakReilly'] else [])+d['employees'];print('email key present:', all('email' in p for p in ppl))"
kill %1 2>/dev/null
```
Expected: `email key present: True`.

- [ ] **Step 7: Commit**

```bash
git add app.py static/js/main.js
git commit -m "Bulletin: manage employee email (add/update backend + modal fields)"
```

---

## Task 5: Bulletin routes — preview + send

**Files:**
- Modify: `app.py` — add two routes in `register_routes` (near the export routes); add module import `from emailer import send_email` and `from bulletin import render_bulletin` at top.

**Interfaces:**
- Consumes: `build_schedule_response`, `get_db`, `render_bulletin`, `send_email`, `Config`.
- Produces: `GET /api/schedule/<week_start>/bulletin/preview`, `POST /api/schedule/<week_start>/bulletin/send`.

- [ ] **Step 1: Add imports**

Near the other top-level imports in `app.py` (after `from openpyxl...` group), add:

```python
import json as _json
from emailer import send_email
from bulletin import render_bulletin
```

- [ ] **Step 2: Add a shared recipients+snapshot helper and the two routes**

Add inside `register_routes` (near the export routes). This helper collects recipients (active + email) and maps each to their shifts from the snapshot:

```python
    def _bulletin_recipients(data):
        """Return (recipients, missing) from a schedule_data snapshot.
        recipients: [{'id','name','email','shifts'}] for active employees WITH an email.
        missing: [names] of active employees WITHOUT an email.
        Shift data comes from the snapshot's people; recipients/missing come from the DB
        (active employees), so people not on this week still get the bulletin.
        """
        people = list(data.get('managers', []))
        if data.get('zakReilly'):
            people.append(data['zakReilly'])
        people.extend(data.get('employees', []))
        shifts_by_id = {p['id']: p['shifts'] for p in people}

        db = get_db()
        rows = db.execute(
            "SELECT id, name, email FROM employees WHERE active = 1 ORDER BY "
            "CASE section WHEN 'manager' THEN 1 WHEN 'zak' THEN 2 ELSE 3 END, sort_order"
        ).fetchall()
        recipients, missing = [], []
        for r in rows:
            email = (r['email'] or '').strip()
            if email:
                recipients.append({
                    'id': r['id'], 'name': r['name'], 'email': email,
                    'shifts': shifts_by_id.get(r['id'], [None] * 7),
                })
            else:
                missing.append(r['name'])
        return recipients, missing

    @app.route('/api/schedule/<week_start>/bulletin/preview', methods=['GET'])
    def bulletin_preview(week_start):
        try:
            data = build_schedule_response(week_start)
            recipients, missing = _bulletin_recipients(data)
            sample_for = recipients[0] if recipients else {'name': 'Preview', 'shifts': [None] * 7}
            _, sample_html, _ = render_bulletin(sample_for, data)
            return jsonify({
                'enabled': Config.EMAIL_ENABLED,
                'recipients': [{'id': r['id'], 'name': r['name'], 'email': r['email']} for r in recipients],
                'missing_email': missing,
                'sample_html': sample_html,
            })
        except Exception as e:
            logging.error(f"Error building bulletin preview: {e}")
            return jsonify({'error': str(e)}), 400

    @app.route('/api/schedule/<week_start>/bulletin/send', methods=['POST'])
    def bulletin_send(week_start):
        if not Config.EMAIL_ENABLED:
            return jsonify({'error': 'Email sending is disabled'}), 403
        try:
            body = request.get_json(silent=True) or {}
            is_test = bool(body.get('test'))
            data = build_schedule_response(week_start)
            recipients, missing = _bulletin_recipients(data)
            smtp = {
                'host': Config.SMTP_HOST, 'port': Config.SMTP_PORT,
                'user': Config.SMTP_USER, 'password': Config.SMTP_PASSWORD,
                'from_addr': Config.EMAIL_FROM, 'from_name': Config.EMAIL_FROM_NAME,
            }
            db = get_db()
            cur = db.execute(
                "INSERT INTO publications (week_start, message_type, snapshot_json, is_test) "
                "VALUES (?, 'bulletin', ?, ?)",
                (week_start, _json.dumps(data), 1 if is_test else 0),
            )
            pub_id = cur.lastrowid

            def _log(emp_id, email, name, subject, status, error=None):
                db.execute(
                    "INSERT INTO email_outbox (publication_id, message_type, employee_id, "
                    "recipient_email, recipient_name, subject, status, error) "
                    "VALUES (?, 'bulletin', ?, ?, ?, ?, ?, ?)",
                    (pub_id, emp_id, email, name, subject, status, error),
                )

            sent = failed = skipped = 0

            if is_test:
                sample = recipients[0] if recipients else {'name': 'Test', 'shifts': [None] * 7}
                subject, html, text = render_bulletin(sample, data)
                try:
                    send_email(smtp, Config.EMAIL_TEST_RECIPIENT, subject, html, text)
                    _log(None, Config.EMAIL_TEST_RECIPIENT, 'TEST', subject, 'sent')
                    sent = 1
                except Exception as e:
                    _log(None, Config.EMAIL_TEST_RECIPIENT, 'TEST', subject, 'failed', str(e))
                    failed = 1
            else:
                for name in missing:
                    _log(None, '', name, None, 'skipped')
                    skipped += 1
                for r in recipients:
                    subject, html, text = render_bulletin(r, data)
                    try:
                        send_email(smtp, r['email'], subject, html, text)
                        _log(r['id'], r['email'], r['name'], subject, 'sent')
                        sent += 1
                    except Exception as e:
                        _log(r['id'], r['email'], r['name'], subject, 'failed', str(e))
                        failed += 1

            db.execute(
                "UPDATE publications SET recipient_count = ?, sent_count = ?, failed_count = ? "
                "WHERE id = ?",
                (len(recipients), sent, failed, pub_id),
            )
            db.commit()
            return jsonify({'publication_id': pub_id, 'sent': sent, 'failed': failed, 'skipped': skipped})
        except Exception as e:
            logging.error(f"Error sending bulletin: {e}")
            return jsonify({'error': str(e)}), 400
```

- [ ] **Step 3: Verify preview + flag-off send + logging**

```bash
cp schedule.db /tmp/schedule.db.bak
./venv/bin/python app.py >/tmp/t5.log 2>&1 &
sleep 3
WEEK=$(curl -s http://127.0.0.1:5001/api/current-week | ./venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['weekStart'])")
echo "-- preview (expect 200, JSON with recipients/enabled=false) --"
curl -s http://127.0.0.1:5001/api/schedule/$WEEK/bulletin/preview | ./venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print('enabled',d['enabled'],'recips',len(d['recipients']),'missing',len(d['missing_email']),'has_sample',bool(d.get('sample_html')))"
echo "-- send with flag OFF (expect 403) --"
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' -d '{"test":true}' http://127.0.0.1:5001/api/schedule/$WEEK/bulletin/send
kill %1 2>/dev/null
```
Expected: preview line prints `enabled False recips <n> missing <m> has_sample True`; flag-off send prints `403`.

- [ ] **Step 4: Verify a real test-send logs correctly (SMTP mocked — no real email)**

This confirms the send/outbox/publication logic without needing live SMTP creds. It monkeypatches `send_email` to a no-op via a tiny harness:

```bash
cp schedule.db /tmp/schedule.db.bak
EMAIL_ENABLED=true ./venv/bin/python -c "
import app as A, bulletin, json
# stub the network send so we exercise logging without real SMTP
import emailer
A.send_email = lambda *a, **k: None
flask_app = A.create_app()
client = flask_app.test_client()
wk = client.get('/api/current-week').get_json()['weekStart']
r = client.post(f'/api/schedule/{wk}/bulletin/send', json={'test': True})
print('status', r.status_code, r.get_json())
assert r.status_code == 200 and r.get_json()['sent'] == 1
import sqlite3; c = sqlite3.connect(A.Config.DATABASE)
pubs = c.execute('SELECT COUNT(*) FROM publications WHERE is_test=1').fetchone()[0]
ob = c.execute(\"SELECT COUNT(*) FROM email_outbox WHERE status='sent'\").fetchone()[0]
print('publications(test):', pubs, 'outbox sent:', ob)
assert pubs >= 1 and ob >= 1
print('send logging OK')
"
```
Expected: `status 200 {...'sent': 1...}`, `send logging OK`.
(Note: `A.send_email = lambda...` replaces the name the route calls, since the route imported `send_email` into `app`'s namespace.)

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "Bulletin: add preview + send routes with publication snapshot and outbox logging"
```

---

## Task 6: Bulletin UI — toolbar button + Preview & Send modal

**Files:**
- Modify: `static/js/main.js` — add toolbar button + `openBulletinModal()` / `sendBulletin(test)`.

**Interfaces:**
- Consumes: `GET .../bulletin/preview`, `POST .../bulletin/send`.

**Security note (XSS):** This modal uses `insertAdjacentHTML` — the app's established
modal pattern. That is acceptable here ONLY because every dynamic value is neutralized:
`scheduleData.weekTitle` and each `missing_email` name are wrapped in `escapeHtml(...)`,
the counts are numbers, and `data.sample_html` is server-rendered by `bulletin.py`, which
`html.escape`s all employee/schedule-derived content (verified in Task 3 — `'http' not in
html`). Do NOT interpolate any employee-entered value (name/email) into this HTML without
`escapeHtml`. If you add a new dynamic field, escape it.

- [ ] **Step 1: Add the toolbar button**

In `renderToolbar`, after the Time-Off Sheets button block (the `exportTimeOffCalendars()` button, ~line 1582-1584) and before the `window.print()` button, add:

```javascript
                <button class="action-btn" onclick="openBulletinModal()" title="Email this week's schedule to staff">
                    <span class="icon">✉️</span> Email Schedule
                </button>
```

- [ ] **Step 2: Add the modal + send functions**

Add near the other action functions (e.g., after `exportTimeOffCalendars`):

```javascript
async function openBulletinModal() {
    const week = State.currentWeekStart;
    let data;
    try {
        const res = await fetch(`${Config.API_BASE}/api/schedule/${week}/bulletin/preview`);
        if (!res.ok) throw new Error('preview failed');
        data = await res.json();
    } catch (e) {
        alert('Could not build the email preview.');
        return;
    }
    const missing = data.missing_email.length
        ? `<div style="color:#c0392b;margin:8px 0">⚠ ${data.missing_email.length} without email (won't receive): ${data.missing_email.map(escapeHtml).join(', ')}</div>`
        : '';
    const disabledNote = data.enabled ? '' :
        `<div style="color:#c0392b;margin:8px 0">Email sending is OFF (set EMAIL_ENABLED=true on the server). You can still send a test once enabled.</div>`;
    const modalHtml = `
        <div class="modal-overlay active" id="bulletinModal">
            <div class="modal" style="max-width:640px">
                <div class="modal-header">
                    <h3>Email Schedule — Week of ${escapeHtml(scheduleData.weekTitle)}</h3>
                    <button class="close-btn" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div>Recipients: <strong>${data.recipients.length}</strong> staff with email.</div>
                    ${missing}
                    ${disabledNote}
                    <div style="border:1px solid #ddd;border-radius:6px;margin-top:10px;max-height:340px;overflow:auto">
                        ${data.sample_html}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
                    <button class="btn" onclick="sendBulletin(true)" ${data.enabled ? '' : 'disabled'}>Send test to me</button>
                    <button class="btn btn-save" onclick="sendBulletin(false)" ${data.enabled ? '' : 'disabled'}>Send to all staff</button>
                </div>
            </div>
        </div>
    `;
    closeModal();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function sendBulletin(test) {
    if (!test && !confirm('Send this schedule email to ALL staff with an email on file?')) return;
    const week = State.currentWeekStart;
    try {
        const res = await fetch(`${Config.API_BASE}/api/schedule/${week}/bulletin/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ test }),
        });
        const out = await res.json();
        if (!res.ok) throw new Error(out.error || res.status);
        closeModal();
        alert(test
            ? `Test email sent (${out.sent} sent, ${out.failed} failed).`
            : `Sent to staff: ${out.sent} sent, ${out.failed} failed, ${out.skipped} skipped (no email).`);
    } catch (e) {
        alert(`Could not send: ${e.message}`);
    }
}
```

- [ ] **Step 3: Confirm an `escapeHtml` helper exists (or add one)**

Run: `grep -n "function escapeHtml" static/js/main.js`
- If it exists, do nothing.
- If it does NOT exist, add this near the top helper functions:
```javascript
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => (
        {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
```

- [ ] **Step 4: Verify JS + manual smoke**

```bash
node --check static/js/main.js && echo "main.js OK"
```
Then with `./venv/bin/python app.py` running, open `http://127.0.0.1:5001/`, click **✉️ Email Schedule**: the modal shows the recipient count, any missing-email warning, and a rendered preview; the send buttons are disabled with the "email is OFF" note (since `EMAIL_ENABLED` is false locally). Stop the app.

- [ ] **Step 5: Commit**

```bash
git add static/js/main.js
git commit -m "Bulletin: Email Schedule toolbar button + preview/send modal"
```

---

## Task 7: Deployment docs

**Files:**
- Modify: `DEPLOYMENT.md`

- [ ] **Step 1: Document the email setup**

Add a subsection to `DEPLOYMENT.md` (near the env/config steps):

```markdown
### Weekly bulletin email (SMTP)

The "Email Schedule" button and the (future) reminder cron send via SMTP over the
Ice Line mail host. Add to the LXC `.env`:

    EMAIL_ENABLED=false                 # flip to true only after a successful test-send
    SMTP_HOST=securemail2.megamailservers.com
    SMTP_PORT=465                       # implicit SSL
    SMTP_USER=badams@iceline.info
    SMTP_PASSWORD=<the mailbox password>
    EMAIL_FROM=badams@iceline.info
    EMAIL_FROM_NAME=Ice Line Schedule
    EMAIL_TEST_RECIPIENT=badams@iceline.info

Rollout: deploy with `EMAIL_ENABLED=false`, then set it `true`, restart, open a week,
click **Email Schedule → Send test to me**, confirm the email arrives, then use
**Send to all staff**. If Chromium/PDF or anything else is mid-deploy, this is
independent. No new Python dependency (uses stdlib `smtplib`).
```

- [ ] **Step 2: Commit**

```bash
git add DEPLOYMENT.md
git commit -m "Bulletin: document SMTP email env + rollout in DEPLOYMENT.md"
```

---

## Final verification

- [ ] `EMAIL_ENABLED=false` (default): preview works; send returns 403; core scheduling (create/edit/save week, exports) unchanged.
- [ ] With `EMAIL_ENABLED=true` + real `.env` SMTP creds on a machine that can reach the host: **Send test to me** delivers a real email to `badams@iceline.info` that renders correctly (personalized top + full week, no broken images/links).
- [ ] A full send to a small test roster (a couple of employees whose email you control) delivers, and creates one `publications` row + per-recipient `email_outbox` rows with correct sent/failed/skipped counts.
- [ ] Employees with no email show in the preview warning and are logged `skipped`, never crash the send.
