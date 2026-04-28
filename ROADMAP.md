# Ice Line Employee Scheduler - Roadmap

## Vision

A **dead-simple scheduling app** that eliminates text message chaos. Employees know their schedule instantly. Managers see availability at a glance. Time-off requests don't get lost.

**Design Principles:**
- Mobile-first (employees check on their phones)
- One-tap actions (request off, swap shift, confirm)
- Visual clarity (red = conflict, green = covered, yellow = pending)
- Zero training required

---

## Current Status (April 2026)

**Working:**
- Weekly scheduling (Wed-Tue) with shift templates
- Manager admin view with auto-save, undo/redo
- Employee portal (read-only)
- Excel export, backup/restore
- Dark mode
- Hidden Employees panel (seasonal staff lifecycle)

**Missing (Critical):**
- No authentication
- Employees can't submit availability or requests
- No notifications when schedule changes
- No visibility into who's available when

---

## Phase 0: Foundation Safety Fixes

*Goal: Stop the bleeding. These are pre-feature hardening — bugs and risks that compound everything built on top.*

Surfaced via April 2026 dual-AI review (Claude + Codex). Verified against production code.

### 0.1 Concurrency safety
- [ ] Add `version INTEGER NOT NULL DEFAULT 1` to `schedules` table (migration for existing DB)
- [ ] `build_schedule_response` returns `version`
- [ ] `POST /api/schedule/<week_start>` requires `base_version` in payload, runs atomic UPDATE with version check, returns **409 Conflict** on mismatch
- [ ] Client increments local version on each successful save; on 409 reloads schedule and surfaces "Someone else updated this — your changes were lost"
- [ ] Enable SQLite WAL mode and `busy_timeout = 5000` on every connection
- **Why:** production runs 9 gunicorn workers + delete-then-insert saves; two tabs WILL silently overwrite each other today

### 0.2 Restrict CORS
- [ ] Remove the `Access-Control-Allow-Origin: *` after_request hook entirely (same-origin only — `Config.API_BASE` is empty so no cross-origin needs)
- **Why:** wildcard exposes write endpoints to any browser tab on any site

### 0.3 Disable backup import in production
- [ ] Add `BACKUP_IMPORT_ENABLED` env var (default `false`)
- [ ] `POST /api/backup/import` returns 403 unless flag set
- [ ] Hide "Import from Backup" menu item when flag false
- [ ] Leave `/api/backup/export` (read-only) accessible
- **Why:** the import endpoint accepts a JSON file and wipes/reloads the entire DB — currently unauthenticated and reachable on the LAN. Re-enable per-restore via env var when manager auth ships (Phase 3.5)

### 0.4 Whole-week copy: ID-based with warning
- [ ] Change `copyPreviousWeek()` (main.js:438) to map by `employee_id`, matching `copyEmployeePreviousWeek()` (main.js:501)
- [ ] Compute diff before copying: matched / in-prev-only / in-current-only
- [ ] Confirm dialog: "Copy 6 employees? Skipping: Lena (hidden this week), Hunter (didn't work last week)"
- **Why:** current index-based mapping silently copies the wrong employee's shifts when staff order or membership changes

---

## Phase 1: Employee Self-Service Portal

*Goal: Employees can submit requests without texting the manager*

### 1.1 Employee Login (Simple)
- [ ] PIN-based login per employee (4-digit code)
- [ ] Remember device for 30 days
- [ ] No username/password - just select name + enter PIN
- [ ] Manager sets/resets PINs in admin

### 1.2 Availability Submission
- [ ] Weekly availability grid (same Wed-Tue layout)
- [ ] Three states per time slot: **Available**, **Unavailable**, **Preferred**
- [ ] Set recurring patterns ("Never Sundays", "Mornings only on weekdays")
- [ ] Deadline: availability due by [configurable day] for following week
- [ ] Visual reminder on portal if not submitted

**UI Concept:**
```
┌─────────────────────────────────────────────────────┐
│  Your Availability for Jan 15-21                    │
│  ┌─────┬─────┬─────┬─────┬─────┬─────┬─────┐       │
│  │ Wed │ Thu │ Fri │ Sat │ Sun │ Mon │ Tue │       │
│  ├─────┼─────┼─────┼─────┼─────┼─────┼─────┤       │
│  │ AM  │ ✓  │ ✓  │ ✓  │ ✗  │ ✗  │ ✓  │ ✓  │       │
│  │ PM  │ ✓  │ ★  │ ★  │ ✗  │ ✗  │ ✓  │ ✓  │       │
│  └─────┴─────┴─────┴─────┴─────┴─────┴─────┘       │
│  ✓ = Available  ★ = Preferred  ✗ = Unavailable     │
│                                    [Submit]         │
└─────────────────────────────────────────────────────┘
```

### 1.3 Time-Off Requests
- [ ] Request form: date range + reason (optional)
- [ ] Status tracking: Pending → Approved/Denied
- [ ] Manager sees all pending requests in admin dashboard
- [ ] One-click approve/deny with optional note
- [ ] Employee sees request history

**Database Tables:**
```sql
CREATE TABLE time_off_requests (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER,
    start_date DATE,
    end_date DATE,
    reason TEXT,
    status TEXT DEFAULT 'pending',  -- pending, approved, denied
    manager_note TEXT,
    created_at TIMESTAMP,
    resolved_at TIMESTAMP,
    resolved_by INTEGER
);

CREATE TABLE availability (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER,
    week_start DATE,
    day_index INTEGER,  -- 0-6 for Wed-Tue
    am_status TEXT,     -- available, unavailable, preferred
    pm_status TEXT,
    submitted_at TIMESTAMP
);

CREATE TABLE recurring_availability (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER,
    day_of_week INTEGER,  -- 0=Wed, 1=Thu, etc.
    am_status TEXT,
    pm_status TEXT,
    effective_from DATE,
    effective_until DATE  -- NULL = indefinite
);
```

---

## Phase 2: Manager Dashboard Upgrades

*Goal: See everything at a glance, make decisions fast*

### 2.1 Availability Overlay on Schedule
- [ ] Color-code cells based on employee availability
- [ ] Red border = scheduled but marked unavailable (conflict!)
- [ ] Green tint = marked as preferred
- [ ] Gray = not available
- [ ] Toggle: "Show availability" checkbox

### 2.2 Pending Requests Panel
- [ ] Sidebar or top banner showing pending requests count
- [ ] Quick view: "3 time-off requests pending"
- [ ] Click to expand and approve/deny inline
- [ ] Filter: This week | Next week | All

### 2.3 Coverage Warnings
- [ ] Yellow highlight on days with < minimum staff
- [ ] Red highlight on days with NO coverage
- [ ] Configurable minimum per day (e.g., "need 2 staff on weekends")

### 2.4 Smart Suggestions
- [ ] When scheduling, show who's available AND preferred
- [ ] "Ava prefers this shift" indicator
- [ ] "Nate is unavailable" warning before assignment

---

## Phase 3: Notifications & Schedule Distribution

*Goal: Nobody misses a schedule or a change. Replace the manual weekly email.*

**Architectural decisions (April 2026 dual-AI review):**

- **Snapshot model, not pending_changes table.** When a schedule is published, freeze a JSON snapshot of the entire week. `/employee` reads the latest *successful* snapshot, not live data. Eliminates "staff sees half-baked manager edits" entirely.
- **Two distinct tables, not one.** `schedule_publications` for full bulletin sends; `notification_batches` (or `change_alert_publications`) for delta sends. A change alert is a notification event derived from the diff between snapshots — it does NOT supersede the latest full publication, otherwise "latest published" becomes ambiguous.
- **Outbox per recipient/channel with parent batch.** Delivery state lives in `notification_outbox` rows; aggregate state lives on the parent (publication or batch). Lets us resend to one person and track partial failures without losing per-recipient detail.
- **Recipient rule = "employees in published snapshot + always-include extras"** — not hard-coded sections. Auto-handles hidden/seasonal staff. Snapshots freeze contact state at send time.
- **Link-free first bulletin.** No `/static/` logo (use CID-attached/inline base64), no remote CSS, no "view in browser," no preference URLs, no tracking pixels. Until manager auth + public infra exist, emails must not touch the app at all.
- **Preview invalidation.** Previews carry `schedule_version` + `snapshot_hash`. Send endpoint refuses if `schedules.version` changed since preview was generated. Eliminates "Bob previews, edits in another tab, sends stale preview."
- **No debouncing on rapid publishes.** Disable send button while in-flight; surface "Live schedule changed since this preview" warning if version drifted. Debounce is a UI band-aid.

**Send-from:** `badams@icelinequadrinks.com` via the existing `~/.config/iceline/iceline_auth.py` OAuth helper (broaden scope to include `gmail.send`).

**SMS:** Twilio. ~$1.15/mo for the number, ~$0.0079/msg US. Under $5/mo realistic.

### 3.0 Schema Foundation
- [ ] Add `email`, `notify_email`, `notify_sms`, `phone_invalid`, `email_bounced` columns to `employees`
- [ ] **One-command DB backup script** (must run before any migration)
- [ ] Run migrations atomically with rollback on failure

### 3.1 Snapshot Foundation
- [ ] `schedule_publications` table:
  ```
  id, week_start, snapshot_json, snapshot_hash,
  created_from_schedule_version, created_by, status,
  subject, body_html, body_text, recipient_summary_json,
  send_started_at, send_completed_at, queued_at, published_at
  ```
- [ ] Status values: `draft_preview`, `queued`, `sending`, `complete`, `partial_failure`, `failed`, `superseded`
- [ ] Index on `(week_start, status, published_at DESC)` for "latest successful publication"
- [ ] Change `/employee` and `GET /api/schedule/<week>` (when called by employee portal) to read from latest successful publication
- [ ] Manager view continues to read/write live state — unchanged
- [ ] Nginx restrict `/employee` access until auth lands (belt-and-suspenders)

### 3.2 Weekly Bulletin ("Preview & Send")
- [ ] Preview endpoint: builds snapshot in memory (does NOT persist), returns rendered email + `schedule_version` + `snapshot_hash`
- [ ] Send endpoint: validates version unchanged since preview → 409 if drifted; persists publication row with `status=queued`; enqueues outbox rows; flips to `status=sending`/`complete`/`partial_failure` as deliveries resolve
- [ ] **Recipients:** iterate snapshot's employees + configured "always-include" list + ad-hoc BCC extras from send dialog
- [ ] **HTML format:** mobile-readable list-by-day. Office hours, special events, then each person's shift. NOT the wide manager table.
- [ ] CID-attached Ice Line logo only — no `/static/` URLs in the email
- [ ] "Resend to one person" button on publication detail view

### 3.3 Notification Outbox
- [ ] `notification_outbox` table:
  ```
  id, parent_type ('publication'|'batch'), parent_id,
  employee_id (nullable), recipient_name, recipient_type
    ('employee'|'manager'|'extra'), recipient (email/phone),
  channel ('email'|'sms'), status, provider_message_id,
  attempt_count, last_error, idempotency_key,
  queued_at, sent_at
  ```
- [ ] Idempotency key shape: `{parent_id}:{employee_id_or_recipient_hash}:{channel}:{attempt_kind}` — supports intentional resends
- [ ] Status values: `queued`, `sending`, `sent`, `failed`, `skipped` (e.g. employee opted out)
- [ ] Send worker reads queued rows, attempts delivery, updates status + provider_message_id

### 3.4 Change Alerts ("Notify staff of changes")
- [ ] `change_alert_publications` table (or `notification_batches`) — references the source `schedule_publications` rows being diffed, has its own outbox parent role
- [ ] Diff computation: compare current live state against latest successful full publication snapshot
- [ ] Per-affected-employee message body with was/now diff
- [ ] One outbox row per affected employee per enabled channel
- [ ] "Notify staff of N pending changes" button surfaces only when `live_version > last_publication.created_from_schedule_version`

### 3.5 Manager Auth + Public-Facing *(gating step)*
- [ ] Manager login (PIN or password — see Phase 7.1)
- [ ] Close any remaining unauthenticated write endpoints
- [ ] Re-enable `BACKUP_IMPORT_ENABLED` behind auth
- [ ] Cloudflare Tunnel from CT 700; DNS + TLS for `scheduler.icelinequadrinks.com`
- [ ] Only AFTER this lands: emails may include links back to the app, preference/unsubscribe URLs, "view in browser," etc.

### 3.6 Twilio SMS
- [ ] Twilio account + phone number; creds in LXC `.env`
- [ ] Outbox rows with `channel='sms'`
- [ ] Decide replies policy (forward to Bob? auto-respond?). Record opt-in source per employee before first send.
- [ ] Quiet hours: don't deliver SMS between 9pm–7am local

### 3.7 DaySmart / Dash Integration *(after first bulletin proves the workflow)*
- [ ] Server-side helper calling the `dash` skill / API to fetch ice activity for a date range
- [ ] Per-day cache to avoid re-fetching during preview iterations
- [ ] Layered into the bulletin's per-day content (program names + times only — keep scannable)
- [ ] Optional: "Today on the ice" widget on manager view

### 3.8 Push Notifications (PWA) — *deferred indefinitely*
- Lower priority than email/SMS. Reconsider only if PWA install adoption proves out.

### Build order when ready
1. **Phase 0** safety fixes (in progress — see top of doc)
2. **3.0** schema + backup script
3. **3.1** snapshot foundation + `/employee` reads from snapshots
4. **3.2 + 3.3** Gmail-only link-free bulletin with publication status, outbox, preview invalidation, resend
5. **Nightly off-box backups + restore drill** (see Phase 7.4)
6. **3.5** manager auth + public infra
7. **3.4** change alerts via snapshot diff + outbox
8. **3.6** Twilio SMS as parallel channel
9. **3.7** DaySmart integration
10. (Deferred: 3.8 push)

---

## Phase 4: Shift Swapping

*Goal: Employees handle coverage, manager just approves*

### 4.1 Request a Swap
- [ ] Employee taps shift → "Request coverage"
- [ ] Select reason: "Can't work", "Want to trade", "Other"
- [ ] System shows who's available that day
- [ ] Employee can request specific person or "anyone"

### 4.2 Claim a Shift
- [ ] Available shifts shown on employee portal
- [ ] "Open Shifts" section at top
- [ ] One-tap to claim (pending manager approval)

### 4.3 Manager Approval
- [ ] See all pending swaps
- [ ] Auto-approve option for trusted employees
- [ ] Deny with reason

**Flow:**
```
Ava can't work Saturday → Posts shift as "needs coverage"
                       → Nate sees it, taps "I'll take it"
                       → Manager gets notification
                       → Manager approves
                       → Both Ava and Nate notified
                       → Schedule updated automatically
```

---

## Phase 5: Polish & Delight

*Goal: Make it feel professional and trustworthy*

### 5.1 Visual Improvements
- [ ] Smooth animations on state changes
- [ ] Subtle haptic feedback on mobile (vibrate on tap)
- [ ] Skeleton loading states instead of "Loading..."
- [ ] Pull-to-refresh on mobile

### 5.2 Onboarding
- [ ] First-time employee setup: set PIN, confirm phone/email
- [ ] Quick tour: "Here's your schedule", "Tap here to request off"
- [ ] Manager onboarding: "Add your team", "Set office hours"

### 5.3 Branding
- [ ] Custom logo upload
- [ ] Color theme customization
- [ ] "Powered by Ice Line Scheduler" in footer

### 5.4 Offline Support
- [ ] View current schedule offline (cached)
- [ ] Queue requests when offline, sync when back online
- [ ] Clear "offline" indicator

---

## Phase 6: Reporting & Insights

### 6.1 Hours Dashboard
- [ ] Weekly/monthly hours per employee
- [ ] Overtime alerts (approaching 40 hours)
- [ ] Comparison to previous periods

### 6.2 Availability Patterns
- [ ] "Ava typically works weekends"
- [ ] "Coverage is thin on Sundays historically"
- [ ] Help identify staffing patterns

### 6.3 Request Analytics
- [ ] Most common time-off days
- [ ] Average requests per employee
- [ ] Approval rate

---

## Phase 7: Security & Admin

### 7.1 Manager Authentication
- [ ] Proper login for admin (email/password)
- [ ] Password reset via email
- [ ] Session timeout

### 7.2 Role-Based Access
- [ ] Admin (full access)
- [ ] Manager (can edit schedule, approve requests)
- [ ] Employee (view schedule, submit requests only)

### 7.3 Publication & Save History (replaces full audit log)
- [ ] Last N schedule snapshots before each accepted save (history-lite)
- [ ] Publication history: who sent which bulletin/alert when, with delivery summary
- [ ] *Not building:* full who-changed-what audit log — overkill for a 7-person staff. Re-evaluate if compliance ever demands it.

### 7.4 Backup & Recovery
- [ ] Nightly SQLite backup (`.backup` API or VACUUM INTO) inside CT 700
- [ ] Off-LXC copy: rsync to Synology `badamsphotos` over Tailscale, OR push to Google Drive via `iceline_auth.py`
- [ ] Documented restore drill: "what to run if the LXC dies tomorrow"
- [ ] Treat backups as sensitive — they contain employee phone numbers and (after Phase 3) emails

---

## Implementation Priority

**Do First — revised again post-Codex review (April 2026):**
1. **Phase 0 safety fixes** (concurrency/version, CORS, disable backup import, copy-week ID fix) — non-negotiable foundation
2. **3.0 + 3.1** — schema + snapshot model + `/employee` reads from snapshots
3. **3.2 + 3.3** — link-free Gmail bulletin with outbox + preview invalidation + resend
4. **Phase 7.4** — nightly off-box backup + restore drill
5. **3.5** — manager auth + public-facing infra
6. **3.4** — change alerts (depends on snapshot infra)

**Do Second (Quality of Life):**
7. Employee PIN login (1.1)
8. Time-off requests (1.3)
9. **3.6** Twilio SMS as parallel channel
10. Availability submission (1.2)
11. **3.7** DaySmart integration into bulletin
12. Availability overlay on schedule (2.1)
13. Pending requests panel (2.2)
14. Coverage warnings (2.3)

**Do Third (Differentiation):**
15. Shift swapping (Phase 4)
16. Reporting (Phase 6)
17. Recurring weekly templates (cleaner replacement for "copy last week")

---

## Database Schema Additions

```sql
-- Employee authentication
ALTER TABLE employees ADD COLUMN pin_hash TEXT;
ALTER TABLE employees ADD COLUMN email TEXT;
ALTER TABLE employees ADD COLUMN notify_email BOOLEAN DEFAULT 1;
ALTER TABLE employees ADD COLUMN notify_push BOOLEAN DEFAULT 1;

-- Time-off requests
CREATE TABLE time_off_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'pending',
    manager_note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    resolved_by INTEGER,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (resolved_by) REFERENCES employees(id)
);

-- Weekly availability
CREATE TABLE availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    week_start DATE NOT NULL,
    day_index INTEGER NOT NULL,
    morning_status TEXT DEFAULT 'available',
    afternoon_status TEXT DEFAULT 'available',
    evening_status TEXT DEFAULT 'available',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    UNIQUE(employee_id, week_start, day_index)
);

-- Recurring availability patterns
CREATE TABLE recurring_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    morning_status TEXT DEFAULT 'available',
    afternoon_status TEXT DEFAULT 'available',
    evening_status TEXT DEFAULT 'available',
    effective_from DATE,
    effective_until DATE,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

-- Shift swap requests
CREATE TABLE shift_swaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_employee_id INTEGER NOT NULL,
    shift_date DATE NOT NULL,
    shift_in TEXT,
    shift_out TEXT,
    reason TEXT,
    status TEXT DEFAULT 'open',  -- open, claimed, approved, denied, cancelled
    claimed_by INTEGER,
    manager_note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    FOREIGN KEY (original_employee_id) REFERENCES employees(id),
    FOREIGN KEY (claimed_by) REFERENCES employees(id)
);

-- Audit log
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    old_value TEXT,
    new_value TEXT,
    performed_by INTEGER,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT
);

-- Push notification subscriptions
CREATE TABLE push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh TEXT,
    auth TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
```

---

## API Endpoints to Add

```
# Employee Authentication
POST   /api/employee/login          # PIN login
POST   /api/employee/logout

# Availability
GET    /api/availability/:week      # Get availability for week
POST   /api/availability/:week      # Submit availability
GET    /api/availability/recurring  # Get recurring patterns
POST   /api/availability/recurring  # Set recurring pattern

# Time-Off Requests
GET    /api/time-off                # List my requests
POST   /api/time-off                # Create request
GET    /api/time-off/:id            # Get request details
DELETE /api/time-off/:id            # Cancel request (if pending)

# Manager: Time-Off
GET    /api/admin/time-off          # All pending requests
POST   /api/admin/time-off/:id/approve
POST   /api/admin/time-off/:id/deny

# Shift Swaps
GET    /api/swaps/open              # Available shifts to claim
POST   /api/swaps                   # Post shift for coverage
POST   /api/swaps/:id/claim         # Claim a shift
DELETE /api/swaps/:id               # Cancel (if open)

# Manager: Swaps
GET    /api/admin/swaps             # All pending swaps
POST   /api/admin/swaps/:id/approve
POST   /api/admin/swaps/:id/deny

# Notifications
POST   /api/push/subscribe          # Register for push
DELETE /api/push/unsubscribe
```

---

## Quick Reference

| URL | Purpose | Auth Required |
|-----|---------|---------------|
| `/` | Manager scheduler | Manager PIN/Login |
| `/employee` | Employee portal | Employee PIN |
| `/employee/availability` | Submit availability | Employee PIN |
| `/employee/requests` | Time-off requests | Employee PIN |
| `/employee/swaps` | View/claim open shifts | Employee PIN |

---

## Success Metrics

- **Adoption:** 80%+ employees using portal within 2 weeks
- **Reduction:** 50% fewer scheduling-related texts to manager
- **Speed:** Time-off requests resolved within 24 hours
- **Accuracy:** Zero "I didn't know my schedule changed" incidents

---

*Last updated: April 2026 — post dual-AI review (Claude + Codex). Added Phase 0 safety fixes, rewrote Phase 3 with snapshot model + outbox architecture, added Phase 7.4 backup automation.*
