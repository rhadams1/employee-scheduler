# Weekly Bulletin + Notification Foundation — Design (Auto-Emails, Sub-project 1)

**Date:** 2026-06-19
**Status:** Approved (pending spec review)
**Author:** Bob Adams (with Claude)

## Context

Bob manually emails the weekly schedule to staff. This automates it as a one-click
**Preview & Send**, and lays the shared foundation for a broader notification system.
"Auto emails" was scoped (brainstorming, 2026-06-19) to two features, email-only:
1. **Weekly bulletin** — manual Preview & Send (this spec).
2. **Daily shift reminders** — automatic night-before nudge (sub-project 2, separate spec).

This spec is **sub-project 1**: the weekly bulletin plus the notification foundation it
needs (email field, SMTP emailer, delivery log, send snapshot, safety flag). It ships an
independently useful capability: "email the weekly schedule to staff."

## Goals

A manager clicks **Send** on the week they're viewing, previews the email + recipient
list, and sends a **personalized** weekly schedule email ("your shifts" + full week) to
all active staff who have an email — over the Ice Line mail host, with every delivery
logged and the sent week snapshotted. Nothing sends until deliberately enabled, and a
**test-send to self** is always available first.

## Non-goals / deferred (engine won't need rework to add them)

- Daily reminders (sub-project 2), change-alerts, SMS/Twilio, quiet hours.
- Rewiring `/employee` to read from a frozen snapshot.
- Per-employee notification preferences beyond "has an email."
- Unsubscribe/preference links, tracking pixels, "view in browser" (link-free email;
  no public infra yet).

## Constraints

- **Additive; must not break core scheduling** (same rule as the auth work). No changes
  to schedule save/version/autosave logic.
- **`EMAIL_ENABLED` flag, default false** — with it off, the send endpoints refuse
  (preview still works). Nothing can email staff until the flag is set.
- **No secrets committed** — the SMTP password lives only in the LXC `.env`.
- **Auth note:** this branch is based on `main` (no auth yet). The new send/admin
  endpoints follow the app's current unauthenticated state; when the auth foundation
  merges, they must gain `@manager_required` (tracked as a follow-up).

## Email transport (confirmed)

Send via `smtplib.SMTP_SSL` — host `securemail2.megamailservers.com`, **port 465,
implicit SSL**, SMTP auth. Username `badams@iceline.info`, password from `.env`. From /
Reply-To = `badams@iceline.info` (replies reach Bob). NOT Gmail/Google.

## Data model (additive migrations in `init_db`)

```sql
ALTER TABLE employees ADD COLUMN email TEXT;   -- nullable; manager sets it

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start DATE NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'bulletin',
    snapshot_json TEXT NOT NULL,           -- build_schedule_response(week) at send time
    recipient_count INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    is_test INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id INTEGER,                -- nullable; reminders (sub-project 2) reuse this table
    message_type TEXT NOT NULL,            -- 'bulletin' now; 'reminder' later
    employee_id INTEGER,
    recipient_email TEXT NOT NULL,
    recipient_name TEXT,
    subject TEXT,
    status TEXT NOT NULL,                  -- 'sent' | 'failed' | 'skipped'
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE SET NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_publication ON email_outbox(publication_id);
```

`email` is a sensitive-ish field but not a secret; it is fine to serialize to the manager
UI. (If the auth branch's `public_employee()` sanitizer is later merged, `email` should
remain included — it is needed by the admin UI.)

## Config additions (`class Config`, env-driven)

```python
EMAIL_ENABLED = os.environ.get('EMAIL_ENABLED', 'false').lower() == 'true'
SMTP_HOST = os.environ.get('SMTP_HOST', 'securemail2.megamailservers.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER = os.environ.get('SMTP_USER', 'badams@iceline.info')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')   # ONLY from .env; empty in repo
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'badams@iceline.info')
EMAIL_FROM_NAME = os.environ.get('EMAIL_FROM_NAME', 'Ice Line Schedule')
EMAIL_TEST_RECIPIENT = os.environ.get('EMAIL_TEST_RECIPIENT', 'badams@iceline.info')
```

## Components

### 1. `emailer.py` (new module, no import from app.py)
- `send_email(to_addr, subject, html_body, text_body, config)` → sends one message via
  `smtplib.SMTP_SSL(host, port)`, `login(user, password)`, `sendmail`. Builds a
  `MIMEMultipart('alternative')` with text + HTML parts, `From`/`Reply-To` headers.
  Raises on failure (caller catches per-recipient).
- Reads host/port/user/password/from from the passed config (keeps it testable/pure).

### 2. `bulletin.py` (new module — rendering)
- `render_bulletin(employee, schedule_data)` → `(subject, html, text)`. Personalized:
  greeting + "your shifts next week" (that employee's non-empty shifts, or "no shifts
  scheduled"), then a "Full week" section grouped by day (office hours, events, who
  works when). Mobile-friendly HTML with inline styles; **no remote images or links**.
  Subject e.g. `Ice Line schedule — week of {weekTitle}`.
- Pure function of (employee dict, schedule_data dict from `build_schedule_response`).

### 3. Routes (in `register_routes`)
- `GET /api/schedule/<week_start>/bulletin/preview` → JSON:
  `{recipients: [{id, name, email|null}], missing_email: [names], sample_html, enabled: bool}`.
  `sample_html` = `render_bulletin` for the first recipient (or the manager) so the UI
  shows a real preview. Always works, even when `EMAIL_ENABLED` is false.
- `POST /api/schedule/<week_start>/bulletin/send` — body `{test: bool}`:
  - If `EMAIL_ENABLED` is false → `403 {error: 'Email sending is disabled'}`.
  - Build `data = build_schedule_response(week_start)`.
  - **Recipients:** all `active = 1` employees with a non-empty `email`. (Employees
    without an email are recorded as `skipped` in the outbox so they surface.)
  - `test: true` → send a single email to `EMAIL_TEST_RECIPIENT`, rendered as if for the
    manager; create a `publications` row with `is_test = 1`; one outbox row.
  - `test: false` → create a `publications` row (snapshot), then per recipient:
    `render_bulletin` → `send_email` → outbox row (`sent`/`failed` + error). One failure
    does not abort the batch. Update publication counts.
  - Returns `{sent, failed, skipped, publication_id}`.
- **Employee email management:** extend the existing `add_employee` (POST) and
  `update_employee` (PUT) handlers to accept and persist an `email` field. No new route.

### 4. Front-end (`main.js`, `index.html`)
- **Edit Employee modal** (`openEmployeeModal`/`saveEmployee`) and **Add Employee**
  modal gain an **Email** input, saved via the existing PUT/POST.
- **Toolbar:** an **"✉️ Email Schedule"** button (near the PDF button) opens a
  **preview modal**: recipient count, a "⚠ N have no email: …" warning, the rendered
  `sample_html` in an iframe/preview area, and two actions — **"Send test to me"** and
  **"Send to all staff"** (the latter behind a confirm). Disabled with an explanatory
  note when `enabled` is false.

## Data flow

```
Manager clicks ✉️ Email Schedule (viewing week W)
  GET /api/schedule/W/bulletin/preview
    -> recipients + missing-email list + sample rendered email
  [Send test to me]  -> POST .../bulletin/send {test:true}
    -> send_email(EMAIL_TEST_RECIPIENT) ; publication(is_test) ; 1 outbox row
  [Send to all]      -> POST .../bulletin/send {test:false}
    -> publication(snapshot of W)
       for each active employee with email:
         render_bulletin(emp, data) -> send_email -> outbox(sent|failed)
       employees w/o email -> outbox(skipped)
    -> {sent, failed, skipped, publication_id}
```

## Error handling
- `EMAIL_ENABLED` false → send endpoints 403 with a clear message; preview still returns.
- SMTP connection/auth failure on a real send → the first `send_email` raises; catch at the
  batch level, mark remaining recipients `failed` (or abort with a clear error if the SMTP
  *connection* can't be established at all), and return a non-200 with the reason. Per-
  recipient send errors are caught individually and logged; the batch continues.
- Missing/blank recipient email → `skipped` outbox row, never a hard error.
- All exceptions logged via `logging`; the endpoint never 500s silently.

## Testing (manual — no automated suite, per project norm)
- **Render:** `python -c` calling `render_bulletin` on a sample employee + a real
  `build_schedule_response` week; eyeball subject/text/HTML; confirm no remote URLs.
- **Test-send:** with `EMAIL_ENABLED=true` and real `.env` SMTP creds, POST
  `{test:true}` and confirm an email arrives at `badams@iceline.info`.
- **Flag off:** POST send → 403; preview → 200.
- **Full send (to a safe test roster):** set a couple of employees' emails to addresses
  you control, send, confirm arrival + a `publications` row + per-recipient `email_outbox`
  rows (sent/skipped) with correct counts.
- **Missing email:** an employee with no email → `skipped`, surfaced in preview warning.
- **Core regression:** schedule create/edit/save, exports still work (additive check).

## Deployment
- Add to the LXC `.env`: `EMAIL_ENABLED`, `SMTP_PASSWORD`, and any non-default SMTP
  settings. Document in `DEPLOYMENT.md`. Roll out with `EMAIL_ENABLED=false`, do a
  test-send to self, then enable.
- `.env.example` gains the new keys (with the password blank).
