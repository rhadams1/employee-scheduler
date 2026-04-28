# Ice Line Employee Scheduler - Roadmap

## Vision

A **dead-simple scheduling app** that eliminates text message chaos. Employees know their schedule instantly. Managers see availability at a glance. Time-off requests don't get lost.

**Design Principles:**
- Mobile-first (employees check on their phones)
- One-tap actions (request off, swap shift, confirm)
- Visual clarity (red = conflict, green = covered, yellow = pending)
- Zero training required

---

## Current Status (February 2026)

**Working:**
- Weekly scheduling (Wed-Tue) with shift templates
- Manager admin view with auto-save, undo/redo
- Employee portal (read-only)
- Excel export, backup/restore
- Dark mode

**Missing (Critical):**
- No authentication
- Employees can't submit availability or requests
- No notifications when schedule changes
- No visibility into who's available when

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

**Design decisions from April 2026 brainstorm:**
- Two distinct flows: **Weekly Bulletin** (full week, sent on demand) and **Change Alerts** (batched edits to a published week).
- Both flows go via **email + SMS**, configurable per employee.
- Send-from is `badams@icelinequadrinks.com` via the existing `iceline_auth.py` OAuth helper (need to broaden scope to include Gmail send). Replies route to Bob's inbox naturally.
- Explicit "Send Schedule" / "Publish Changes" buttons — never auto-fire on save. No draft/publish state machine; just on-demand actions with a published_at timestamp on each weekly schedule.
- SMS via Twilio: ~$1.15/mo for the number, ~$0.0079/msg US. Realistic monthly cost for this staff size: under $5.

### 3.0 Prerequisites
- [ ] Add `email`, `notify_email` (bool), `notify_sms` (bool) columns to `employees` table
- [ ] UI in employee edit modal to set email + per-channel opt-ins
- [ ] Broaden `~/.config/iceline/oauth_client.json` scopes to include `gmail.send`; re-authorize once
- [ ] Twilio account + phone number; store creds in LXC `.env`

### 3.1 Weekly Bulletin ("Send Schedule")
- [ ] **Recipients:** active staff + managers + Zak by default; per-send "BCC extras" field for ad-hoc broadening
- [ ] **Trigger:** "Preview & Send Bulletin" button in manager view — preview first, then send
- [ ] **Content:** one section per day Wed–Tue with:
  - Office hours
  - Each employee's shifts that day
  - DaySmart programs/sessions for that day (names + times only — Public Skate, Open Hockey, MSL games, Learn-to-Skate, etc.) via the `dash` skill
  - Holidays
  - Any per-day "Special Events" already captured in the events table
- [ ] **Mechanism:** Gmail API (no SMTP relay needed)
- [ ] Sets `published_at` on the weekly schedule row when sent

### 3.2 Change Alerts ("Publish Changes")
- [ ] Track "pending changes since last_published_at" — every shift edit logs to a `pending_changes` table
- [ ] Top-of-view counter: "5 pending changes — Notify staff"
- [ ] One click → batches changes into one email/SMS per affected employee with the diff (was/now)
- [ ] Resets pending count on send
- [ ] Same opt-in flags as bulletin

### 3.3 Push Notifications (PWA) — *deferred*
- [ ] Service worker for push notifications
- [ ] "Your schedule for next week is posted" / "Your shift on Saturday changed" / "Time-off request approved"
- [ ] Lower priority than email/SMS — depends on PWA install adoption

### 3.4 DaySmart / Dash Integration
- [ ] Build a server-side helper that calls the `dash` skill (or its underlying API) to fetch ice activity for a given date range
- [ ] Cache per-day results to avoid re-fetching during preview iterations
- [ ] Surface in: weekly bulletin, "today's overview" widget on manager view, optional employee portal "what's on the ice today"

### 3.5 Public-Facing Infrastructure *(prerequisite for sending links to staff)*
- [ ] Cloudflare Tunnel from CT 700 (or Tailscale Funnel) so `https://scheduler.icelinequadrinks.com` resolves externally
- [ ] **Blocker:** currently anyone with the URL can edit the schedule. Need at least manager auth (Phase 7.1) before public exposure. Otherwise emails should embed PDFs/HTML and not link back.
- [ ] DNS + TLS via Cloudflare

### Build order when ready
1. 3.0 prerequisites (email column, UI, OAuth scope)
2. 3.1 weekly bulletin without DaySmart (just staff/office hours)
3. 3.4 layer DaySmart program data into the bulletin
4. 3.2 change-alert tracking + send button
5. Twilio SMS as a parallel channel for both 3.1 and 3.2
6. *Separate track:* 3.5 public-facing + Phase 7.1 manager auth

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

### 7.3 Audit Log
- [ ] Who changed what, when
- [ ] "Bob changed Ava's Saturday shift at 3:42 PM"
- [ ] Exportable for records

---

## Implementation Priority

**Do First (Biggest Impact) — revised April 2026:**
1. **Weekly Bulletin email (3.1) + DaySmart integration (3.4)** — replaces Bob's manual weekly email, biggest day-to-day pain
2. Change Alerts (3.2)
3. Employee PIN login (1.1)
4. Time-off requests (1.3)
5. Availability submission (1.2)
6. Availability overlay on schedule (2.1)

**Do Second (Quality of Life):**
7. Pending requests panel (2.2)
8. Push notifications (3.3)
9. Coverage warnings (2.3)

**Do Third (Differentiation):**
10. Shift swapping (Phase 4)
11. Manager authentication (7.1) + public-facing (3.5) — paired
12. Reporting (Phase 6)

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

*Last updated: April 2026 (Phase 3 expanded with concrete bulletin/change-alert design + DaySmart integration)*
