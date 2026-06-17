# Auth Foundation — Design (Phase 1, Sub-project A)

**Date:** 2026-06-17
**Status:** Approved (pending spec review)
**Author:** Bob Adams (with Claude)

## Context

The app has **no authentication**. The manager scheduler at `/` and every write/admin
API are open to anyone who can reach the server. Today that's tolerable only because the
app is LAN-only (`192.1.1.171`, no public DNS/TLS).

Phase 1 (employee self-service) is "mobile-first" — employees check on their phones — so
the app must become reachable from anywhere. The moment it's public, the unauthenticated
manager surface is an open door. Bob chose to **bring public access forward** and to
**build in-app auth** (rather than edge auth).

This spec covers **sub-project A: the auth foundation only.** The Cloudflare Tunnel
(B), time-off requests (C), and availability (D) are separate specs/cycles.

## Hard constraint (Bob)

**Core schedule editing and creation must not break.** Auth is being added *in front of*
a working, in-daily-use scheduler. The design is therefore **additive** and **reversible**:
- Protection is applied via route decorators + a `before_request` gate. The scheduler's
  save/version/autosave/undo/copy-week/employee-CRUD logic is **not modified**.
- A feature flag `AUTH_ENABLED` (default **false**) lets prod revert to today's behavior
  instantly if anything regresses.
- A manual regression checklist (no automated tests exist) is run before/after rollout.

## Goal

A single session-based auth layer with two roles — **manager** and **employee** — that:
1. Protects the scheduler page and all mutating/admin endpoints (manager only).
2. Gates the employee portal and (future) self-service endpoints (employee login).
3. Is safe on a public URL: hashed credentials, lockout on brute force, secure cookies.
4. Can be rolled out and rolled back without touching scheduler logic.

## Identity & credential model

Reuse the existing `employees` table (managers Bob & Dave are already rows).

**Schema additions** (SQLite migration, additive columns, run inside the existing
`init_db` migration block with a backup taken first):
```sql
ALTER TABLE employees ADD COLUMN role TEXT NOT NULL DEFAULT 'employee';  -- 'manager' | 'employee'
ALTER TABLE employees ADD COLUMN username TEXT;          -- login handle (unique, nullable until set)
ALTER TABLE employees ADD COLUMN password_hash TEXT;     -- managers
ALTER TABLE employees ADD COLUMN pin_hash TEXT;          -- employees
ALTER TABLE employees ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE employees ADD COLUMN locked_until TIMESTAMP;
```
- A partial unique index on `username` where `username IS NOT NULL`.
- `role` is set explicitly (Bob, Dave → `manager`; everyone else → `employee`). Not derived
  from `section`, so manager rights are independent of the schedule's manager/zak/staff
  grouping.

**Two credential tiers (one session system):**
- **Manager → password.** A 4-digit PIN is far too weak for a write-everything account on
  a public URL. Hashed with `werkzeug.security.generate_password_hash` (PBKDF2).
- **Employee → 4-digit PIN + lockout.** Convenient on mobile, low-stakes, but useless
  without rate-limiting. Also hashed (never stored plaintext).

**Login identification:** employee **types their name/username** + PIN. No public
roster dropdown (avoids leaking the staff list on a public login page). Manager logs in
with username + password.

## Sessions

- Flask signed-cookie session (`SECRET_KEY` already configured). Store `user_id` and
  `role` only.
- **Employee:** `session.permanent = True` with `PERMANENT_SESSION_LIFETIME = 30 days`
  ("remember this device 30 days").
- **Manager:** non-permanent / ~12h lifetime (shorter for the privileged role).
- Cookie flags: `SESSION_COOKIE_SECURE=True`, `HttpOnly`, `SameSite=Lax`. (HTTPS is
  provided by the tunnel in sub-project B; in LAN dev, Secure can be toggled off via
  config.)

## Auth surfaces (routes)

New:
- `GET/POST /login` — manager login (username + password). On success → manager session,
  redirect to `/`.
- `GET/POST /employee/login` — employee login (name/username + PIN). On success →
  employee session (30-day), redirect to `/employee`.
- `POST /logout` (or `GET /logout`) — clears session for either role.

Two decorators + a helper:
- `@manager_required` — 401/redirect to `/login` unless `session.role == 'manager'`.
- `@employee_required` — 401/redirect to `/employee/login` unless the user is logged in
  (manager or employee both satisfy, since managers may view the portal).
- When `AUTH_ENABLED` is false, both decorators are **no-ops** (today's behavior).

## Route protection map

**`@manager_required`** (the scheduler page + everything that writes or is admin-only):
- `GET /` (manager scheduler page)
- `POST /api/schedule/<week_start>`
- `POST /api/schedule/<week_start>/shift`
- `POST /api/employees`, `PUT /api/employees/<id>`, `DELETE /api/employees/<id>`,
  `POST /api/employees/<id>/restore`
- `GET /api/employees` (full roster — manager only)
- `GET/POST /api/notes/<week>/<id>`
- `GET /api/schedule/<week>/export` (Excel), `GET /api/schedule/<week>/export-pdf`,
  `GET /api/timeoff-calendars` (manager outputs)
- `GET /api/backup/export`, `POST /api/backup/import` (import already gated by
  `BACKUP_IMPORT_ENABLED`; add auth on top)

**Any authenticated user** (manager OR employee — shared reads the portal needs):
- `GET /api/current-week`
- `GET /api/schedule/<week_start>` (the read the employee portal renders from)

**`@employee_required`** (any logged-in user):
- `GET /employee`, `GET /employee/` (portal page)

## Manager credential & PIN administration

For the feature to be operable, manager must be able to set employee PINs and there must
be a way to set the first manager password.

- **Bootstrap CLI** (Flask CLI command), needed because you can't log in to set the first
  password:
  - `flask set-manager-password <username>` — prompts for a password, sets `role='manager'`,
    `username`, `password_hash`.
  - `flask set-employee-pin <employee_id|username>` — sets a PIN (also usable before the
    admin UI exists).
- **Minimal manager admin UI** (in the existing manager view): set/reset an employee's
  username + PIN, and reset a locked account. Kept minimal — full account management is
  future work. This is in scope because employees otherwise can't log in.

## Rate limiting / lockout

- On failed login: increment `failed_attempts`; at **5** set `locked_until = now + 15min`.
- While `locked_until` is in the future, reject with "account temporarily locked."
- On success: reset `failed_attempts = 0`, `locked_until = NULL`.
- Per-account (simple, in-DB). Per-IP throttling can be added later at the tunnel/Cloudflare
  edge.

## Feature flag & rollout (protecting core)

- `AUTH_ENABLED` env var (`Config.AUTH_ENABLED`), default **false**.
- Rollout sequence:
  1. Deploy with `AUTH_ENABLED=false` → **zero behavior change**, verify core still works.
  2. Run migration (DB backed up first), set manager password via CLI, set a couple of
     employee PINs.
  3. Flip `AUTH_ENABLED=true` in a quiet window; restart.
  4. Run the **regression checklist** (below) as the logged-in manager.
  5. Verify an employee session is rejected from admin routes; verify an anonymous request
     is rejected from both.
- **Rollback:** set `AUTH_ENABLED=false`, restart. Scheduler logic untouched, so this is
  always safe.

## Error handling

- API routes under auth return **401** (JSON `{error: 'auth required'}`) for XHR; page
  routes redirect to the appropriate login.
- Locked accounts return a clear, non-enumerating message ("invalid credentials or account
  locked") to avoid confirming which usernames exist.
- Login failures do not reveal whether the username or the secret was wrong.

## Testing

No automated suite exists. Verification is manual.

**Auth-specific manual tests:**
- Manager login success/failure; lockout after 5 failures; unlock after 15 min (or via
  admin reset).
- Employee login success/failure; 30-day cookie persists across browser restart.
- With `AUTH_ENABLED=true`: anonymous hitting `/` → redirect to `/login`; employee session
  hitting `POST /api/schedule/...` → 401; manager session → full access.
- With `AUTH_ENABLED=false`: every route behaves exactly as today.

**Core regression checklist (run before + after rollout, as manager):**
- Create a new week; edit shifts and confirm autosave; undo/redo; copy previous week;
  add/delete/restore an employee; edit office hours + special events and save; Excel export;
  PDF export (Chromium path renders, not the FPDF fallback).

## Out of scope (later sub-projects / phases)

- Cloudflare Tunnel + DNS/TLS (sub-project B).
- Employee self-service endpoints — time-off (C), availability (D).
- Fine-grained RBAC beyond manager/employee (Phase 7.2).
- Password reset via email, "forgot PIN" self-serve (needs the email channel, Phase 3).
- Per-IP/edge rate limiting and audit logging.
