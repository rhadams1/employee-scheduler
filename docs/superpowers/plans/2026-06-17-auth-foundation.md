# Auth Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a feature-flagged, session-based auth layer with two roles (manager, employee) that protects the scheduler + all write/admin endpoints and gates the employee portal, without modifying any scheduler logic.

**Architecture:** A new `auth.py` module holds credential/lockout helpers, session helpers, and two route decorators (`manager_required`, `employee_required`). The decorators are **no-ops when `AUTH_ENABLED` is false** (today's behavior). Existing routes are protected purely by adding a decorator line — their bodies are untouched. Auth columns are added to the existing `employees` table via additive migration. Bootstrap CLI commands set the first manager password and employee PINs.

**Tech Stack:** Flask 3.1, werkzeug.security (scrypt hashing, already installed), SQLite, Flask signed-cookie sessions, click (bundled with Flask) for CLI.

**Spec:** `docs/superpowers/specs/2026-06-17-auth-foundation-design.md`

## Global Constraints

- **Do not modify scheduler logic.** Protection is additive (decorator lines only). Never edit the body of an existing schedule/employee/notes/export route.
- **`AUTH_ENABLED` defaults to `false`** — with the flag off, every route must behave exactly as it does today.
- **No automated test suite exists** — verification is manual via `curl` (cookie jars) and `./venv/bin/python -c`. Do NOT scaffold pytest.
- **Hash everything**: passwords and PINs via `werkzeug.security.generate_password_hash`; never store plaintext.
- **Lockout values:** 5 failed attempts → 15-minute lock (`AUTH_MAX_FAILED=5`, `AUTH_LOCKOUT_MINUTES=15`).
- Run the app for verification with `./venv/bin/python app.py` (port 5001). Back up `schedule.db` before any run that could mutate it: `cp schedule.db /tmp/schedule.db.bak`.
- Each task commits with a clear message. Do not add `Co-Authored-By` trailers.

---

## Task 1: Config, session settings, and schema migration

**Files:**
- Modify: `app.py` — `class Config` (lines 28–53) and `init_db` migration block (after line ~193).

**Interfaces:**
- Produces: `Config.AUTH_ENABLED` (bool), `Config.AUTH_MAX_FAILED` (int), `Config.AUTH_LOCKOUT_MINUTES` (int); `employees` table gains columns `role, username, password_hash, pin_hash, failed_attempts, locked_until` and a partial unique index `idx_employees_username`.

- [ ] **Step 1: Add auth config to `class Config`**

After the `PDF_RENDER_TIMEOUT_MS` line (line 35), add:

```python
    AUTH_ENABLED = os.environ.get('AUTH_ENABLED', 'false').lower() == 'true'
    # Session cookie hardening. HTTPS comes from the Cloudflare tunnel in prod;
    # SESSION_COOKIE_SECURE stays off for LAN/dev unless explicitly enabled.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # employee "remember this device"
    AUTH_MAX_FAILED = int(os.environ.get('AUTH_MAX_FAILED', '5'))
    AUTH_LOCKOUT_MINUTES = int(os.environ.get('AUTH_LOCKOUT_MINUTES', '15'))
```

(`timedelta` is already imported at the top of `app.py`.)

- [ ] **Step 2: Add the employees auth-column migration**

In `init_db`, immediately after the `schedules.version` migration block (the `if 'version' not in schedule_cols:` block ending ~line 193), add:

```python
    # Auth columns (Phase 1 auth foundation) — additive, safe to re-run on existing DBs
    cursor.execute("PRAGMA table_info(employees)")
    employee_cols = {row[1] for row in cursor.fetchall()}
    if 'role' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN role TEXT NOT NULL DEFAULT 'employee'")
        logging.info("Migrated: added employees.role column")
    if 'username' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN username TEXT")
    if 'password_hash' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN password_hash TEXT")
    if 'pin_hash' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN pin_hash TEXT")
    if 'failed_attempts' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")
    if 'locked_until' not in employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN locked_until TIMESTAMP")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_username "
        "ON employees(username) WHERE username IS NOT NULL"
    )
```

- [ ] **Step 3: Verify migration + flag default**

```bash
cp schedule.db /tmp/schedule.db.bak
./venv/bin/python -c "import ast; ast.parse(open('app.py').read()); print('syntax OK')"
./venv/bin/python -c "
import app  # triggers create_app() -> init_db()
import sqlite3
c = sqlite3.connect('schedule.db'); c.row_factory = sqlite3.Row
cols = {r[1] for r in c.execute('PRAGMA table_info(employees)')}
need = {'role','username','password_hash','pin_hash','failed_attempts','locked_until'}
assert need <= cols, f'missing: {need - cols}'
print('columns OK:', sorted(need))
print('AUTH_ENABLED default:', app.Config.AUTH_ENABLED)
assert app.Config.AUTH_ENABLED is False
print('flag default OK')
"
```
Expected: `columns OK`, `AUTH_ENABLED default: False`, `flag default OK`.

- [ ] **Step 4: Verify app still serves normally (flag off)**

```bash
./venv/bin/python app.py >/tmp/auth_t1.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/          # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/employee  # expect 200
kill %1 2>/dev/null
```
Expected: both `200` (no auth gating yet).

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "Auth: add AUTH_ENABLED config, session settings, employees auth-column migration"
```

---

## Task 2: `auth.py` — credential & lockout helpers

**Files:**
- Create: `auth.py`

**Interfaces:**
- Produces:
  - `set_password(conn, emp_id, password)` — sets `password_hash` and `role='manager'`.
  - `set_pin(conn, emp_id, pin)` — validates 4 digits, sets `pin_hash`. Raises `ValueError` on bad PIN.
  - `verify_login(conn, identifier, secret, expected_role) -> (emp_id|None, reason|None)` where `reason in {'invalid','locked'}`. Handles lockout counting.
  - `conn` is a `sqlite3.Connection` with `row_factory = sqlite3.Row`.

- [ ] **Step 1: Create `auth.py` with credential + lockout helpers**

```python
"""Authentication helpers for the Ice Line scheduler.

Pure of any import from app.py (avoids circular imports). DB-touching functions
take an explicit sqlite3 connection (row_factory=sqlite3.Row); decorators/session
helpers (added in a later task) use only flask.session.
"""
from datetime import datetime, timedelta

from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash


def set_password(conn, emp_id, password):
    """Set a manager password and promote the row to role='manager'."""
    if not password:
        raise ValueError("password must not be empty")
    conn.execute(
        "UPDATE employees SET password_hash = ?, role = 'manager' WHERE id = ?",
        (generate_password_hash(password), emp_id),
    )
    conn.commit()


def set_pin(conn, emp_id, pin):
    """Set a 4-digit employee PIN (hashed)."""
    if not (isinstance(pin, str) and pin.isdigit() and len(pin) == 4):
        raise ValueError("PIN must be exactly 4 digits")
    conn.execute(
        "UPDATE employees SET pin_hash = ? WHERE id = ?",
        (generate_password_hash(pin), emp_id),
    )
    conn.commit()


def _account_locked(row):
    locked_until = row["locked_until"]
    if not locked_until:
        return False
    try:
        return datetime.fromisoformat(locked_until) > datetime.now()
    except (TypeError, ValueError):
        return False


def verify_login(conn, identifier, secret, expected_role):
    """Check a login attempt.

    Returns (emp_id, None) on success; (None, 'locked') if the account is locked
    (or just became locked); (None, 'invalid') otherwise. Matches an active
    employee by username first, then by name; ambiguous/zero matches are 'invalid'.
    """
    rows = conn.execute(
        "SELECT * FROM employees WHERE active = 1 AND "
        "(lower(username) = lower(?) OR lower(name) = lower(?))",
        (identifier, identifier),
    ).fetchall()
    if len(rows) != 1:
        return (None, "invalid")
    row = rows[0]

    if _account_locked(row):
        return (None, "locked")

    secret_hash = row["password_hash"] if expected_role == "manager" else row["pin_hash"]
    role_ok = (row["role"] == "manager") if expected_role == "manager" else True

    if secret_hash and role_ok and check_password_hash(secret_hash, secret):
        conn.execute(
            "UPDATE employees SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return (row["id"], None)

    # Failure: increment attempts; lock after the configured threshold.
    attempts = (row["failed_attempts"] or 0) + 1
    locked_until = None
    if attempts >= current_app.config.get("AUTH_MAX_FAILED", 5):
        mins = current_app.config.get("AUTH_LOCKOUT_MINUTES", 15)
        locked_until = (datetime.now() + timedelta(minutes=mins)).isoformat()
        attempts = 0
    conn.execute(
        "UPDATE employees SET failed_attempts = ?, locked_until = ? WHERE id = ?",
        (attempts, locked_until, row["id"]),
    )
    conn.commit()
    return (None, "locked" if locked_until else "invalid")
```

- [ ] **Step 2: Verify helpers against a throwaway DB**

```bash
./venv/bin/python -c "
import sqlite3, app
from auth import set_pin, set_password, verify_login
a = app.create_app()
with a.app_context():
    c = sqlite3.connect(':memory:'); c.row_factory = sqlite3.Row
    c.execute('CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1, role TEXT DEFAULT \"employee\", username TEXT, password_hash TEXT, pin_hash TEXT, failed_attempts INTEGER DEFAULT 0, locked_until TIMESTAMP)')
    c.execute(\"INSERT INTO employees (id,name) VALUES (1,'Ava Hawthorne')\"); c.commit()
    set_pin(c, 1, '1234')
    assert verify_login(c, 'Ava Hawthorne', '1234', 'employee')[0] == 1, 'good pin should pass'
    assert verify_login(c, 'Ava Hawthorne', '0000', 'employee')[0] is None, 'bad pin should fail'
    # lockout after 5 total bad attempts (already 1 used above)
    reasons = [verify_login(c, 'Ava Hawthorne', '0000', 'employee')[1] for _ in range(4)]
    print('reasons:', reasons)
    assert reasons[-1] == 'locked', 'should lock on 5th failure'
    assert verify_login(c, 'Ava Hawthorne', '1234', 'employee')[1] == 'locked', 'locked blocks even correct pin'
    # manager path
    set_password(c, 1, 'hunter2pw')
    assert verify_login(c, 'Ava Hawthorne', 'hunter2pw', 'manager')[0] == 1
    try:
        set_pin(c, 1, '12'); assert False
    except ValueError: pass
    print('auth helpers OK')
"
```
Expected: prints reasons list ending in `locked`, then `auth helpers OK`.

- [ ] **Step 3: Commit**

```bash
git add auth.py
git commit -m "Auth: add credential and lockout helpers (auth.py)"
```

---

## Task 3: Bootstrap CLI commands

**Files:**
- Create: `cli.py`
- Modify: `app.py` — call `register_cli(app)` inside `create_app` (after `register_routes(app)`, ~line 76).

**Interfaces:**
- Consumes: `auth.set_password`, `auth.set_pin` (Task 2).
- Produces: `register_cli(app)`; CLI commands `flask set-manager-password <identifier>` and `flask set-employee-pin <identifier>`.

- [ ] **Step 1: Create `cli.py`**

```python
"""Bootstrap CLI commands for setting credentials before/without the admin UI.

Usage:
  ./venv/bin/flask --app app.py set-manager-password bob
  ./venv/bin/flask --app app.py set-employee-pin ava
"""
import sqlite3

import click

import auth
from app import Config


def _connect():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _find_employee(conn, identifier):
    return conn.execute(
        "SELECT id, name, username FROM employees WHERE active = 1 AND "
        "(lower(username) = lower(?) OR lower(name) = lower(?))",
        (identifier, identifier),
    ).fetchall()


def register_cli(app):
    @app.cli.command("set-manager-password")
    @click.argument("identifier")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def set_manager_password(identifier, password):
        conn = _connect()
        rows = _find_employee(conn, identifier)
        if len(rows) != 1:
            click.echo(f"Expected exactly one match for '{identifier}', found {len(rows)}.")
            return
        emp = rows[0]
        if not emp["username"]:
            conn.execute("UPDATE employees SET username = ? WHERE id = ?",
                         (identifier.strip().lower(), emp["id"]))
            conn.commit()
        auth.set_password(conn, emp["id"], password)
        click.echo(f"Manager password set for {emp['name']} (role=manager).")
        conn.close()

    @app.cli.command("set-employee-pin")
    @click.argument("identifier")
    @click.option("--pin", prompt=True, hide_input=True)
    def set_employee_pin(identifier, pin):
        conn = _connect()
        rows = _find_employee(conn, identifier)
        if len(rows) != 1:
            click.echo(f"Expected exactly one match for '{identifier}', found {len(rows)}.")
            return
        emp = rows[0]
        if not emp["username"]:
            conn.execute("UPDATE employees SET username = ? WHERE id = ?",
                         (identifier.strip().lower(), emp["id"]))
            conn.commit()
        try:
            auth.set_pin(conn, emp["id"], pin)
        except ValueError as e:
            click.echo(f"Error: {e}")
            return
        click.echo(f"PIN set for {emp['name']}.")
        conn.close()
```

(`from app import Config` is safe: `cli.py` is imported by `app.py` only *inside* `create_app` via `register_cli`, after `Config` is defined.)

- [ ] **Step 2: Wire `register_cli` into the factory**

In `app.py` `create_app`, after `register_routes(app)` (line ~76), add:

```python
    # Register CLI commands (bootstrap credentials)
    from cli import register_cli
    register_cli(app)
```

- [ ] **Step 3: Verify the CLI sets credentials**

```bash
cp schedule.db /tmp/schedule.db.bak
printf 'testpass123\ntestpass123\n' | ./venv/bin/flask --app app.py set-manager-password bob
./venv/bin/python -c "
import sqlite3
c = sqlite3.connect('schedule.db'); c.row_factory = sqlite3.Row
r = c.execute(\"SELECT role, username, password_hash FROM employees WHERE lower(name)='bob adams'\").fetchone()
assert r['role'] == 'manager' and r['password_hash'], 'manager password/role not set'
print('manager bootstrap OK:', r['username'], r['role'])
"
printf '4321\n' | ./venv/bin/flask --app app.py set-employee-pin ava
./venv/bin/python -c "
import sqlite3
c = sqlite3.connect('schedule.db'); c.row_factory = sqlite3.Row
r = c.execute(\"SELECT pin_hash FROM employees WHERE lower(name)='ava hawthorne'\").fetchone()
assert r['pin_hash'], 'pin not set'
print('employee pin bootstrap OK')
"
```
Expected: `manager bootstrap OK: bob manager`, `employee pin bootstrap OK`.

- [ ] **Step 4: Commit**

```bash
git add cli.py app.py
git commit -m "Auth: bootstrap CLI for manager password and employee PIN"
```

---

## Task 4: `auth.py` — session helpers + role decorators

**Files:**
- Modify: `auth.py` (append session helpers + decorators).

**Interfaces:**
- Consumes: `flask.session`, `flask.current_app` config `AUTH_ENABLED`.
- Produces:
  - `login_user(emp_id, role, permanent)`, `logout_user()`, `current_user() -> {'id','role'}|None`.
  - `manager_required(f)`, `employee_required(f)` decorators. No-ops when `AUTH_ENABLED` is false. On denial: JSON 401 for `/api/*` paths, redirect to `/login` (manager) or `/employee/login` (employee) otherwise.

- [ ] **Step 1: Append session helpers + decorators to `auth.py`**

Add these imports to the top of `auth.py` (merge with existing imports):

```python
from functools import wraps

from flask import current_app, redirect, request, session
```

Then append:

```python
def login_user(emp_id, role, permanent):
    session.clear()
    session["user_id"] = emp_id
    session["role"] = role
    session.permanent = permanent


def logout_user():
    session.clear()


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return {"id": uid, "role": session.get("role")}


def _deny(scope):
    if request.path.startswith("/api/"):
        from flask import jsonify
        return jsonify({"error": "authentication required"}), 401
    return redirect("/login" if scope == "manager" else "/employee/login")


def manager_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_ENABLED"):
            return f(*args, **kwargs)
        if session.get("role") != "manager":
            return _deny("manager")
        return f(*args, **kwargs)
    return wrapper


def employee_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_ENABLED"):
            return f(*args, **kwargs)
        if session.get("user_id") is None:
            return _deny("employee")
        return f(*args, **kwargs)
    return wrapper
```

- [ ] **Step 2: Verify decorators (flag off = pass-through, flag on = gate)**

```bash
./venv/bin/python -c "
import app
from auth import manager_required, employee_required

@manager_required
def mgr(): return 'ok'
@employee_required
def emp(): return 'ok'

# Flag OFF -> no-op even with no session
a = app.create_app(); a.config['AUTH_ENABLED'] = False
with a.test_request_context('/'):
    assert mgr() == 'ok' and emp() == 'ok'
print('flag off: pass-through OK')

# Flag ON -> denied without session
a.config['AUTH_ENABLED'] = True
with a.test_request_context('/api/x'):
    r = mgr(); assert r[1] == 401, r
    r2 = emp(); assert r2[1] == 401, r2
print('flag on, /api: 401 OK')
with a.test_request_context('/'):
    r = mgr(); assert getattr(r, 'status_code', None) in (301,302), r
print('flag on, page: redirect OK')
"
```
Expected: `flag off: pass-through OK`, `flag on, /api: 401 OK`, `flag on, page: redirect OK`.

- [ ] **Step 3: Commit**

```bash
git add auth.py
git commit -m "Auth: add session helpers and manager/employee route decorators"
```

---

## Task 5: Login / logout routes + templates

**Files:**
- Modify: `app.py` — import line (16) add `session, redirect`; add three routes in `register_routes` near `index` (after the `employee_portal` route, ~line 660).
- Create: `templates/login.html`, `templates/employee_login.html`.

**Interfaces:**
- Consumes: `auth.verify_login`, `auth.login_user`, `auth.logout_user`; `get_db()` (existing, returns a `sqlite3.Row` connection).
- Produces: routes `GET/POST /login`, `GET/POST /employee/login`, `GET/POST /logout`.

- [ ] **Step 1: Extend the flask import and add auth imports in `app.py`**

Change line 16 from:

```python
from flask import Flask, jsonify, request, send_file, render_template, g
```
to:
```python
from flask import Flask, jsonify, request, send_file, render_template, g, session, redirect
```

Add near the other top-level imports (after the `from fpdf import FPDF` group, ~line 22):

```python
from auth import (
    manager_required, employee_required,
    login_user, logout_user, verify_login,
)
```

- [ ] **Step 2: Add the login/logout routes**

In `register_routes`, right after the `employee_portal` route (ends ~line 660), add:

```python
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = (request.form.get('username') or '').strip()
            password = request.form.get('password') or ''
            emp_id, reason = verify_login(get_db(), username, password, 'manager')
            if emp_id:
                login_user(emp_id, 'manager', permanent=False)
                return redirect('/')
            msg = ('Account temporarily locked. Try again later.'
                   if reason == 'locked' else 'Invalid credentials.')
            return render_template('login.html', error=msg), 401
        return render_template('login.html', error=None)

    @app.route('/employee/login', methods=['GET', 'POST'])
    def employee_login():
        if request.method == 'POST':
            identifier = (request.form.get('name') or '').strip()
            pin = request.form.get('pin') or ''
            emp_id, reason = verify_login(get_db(), identifier, pin, 'employee')
            if emp_id:
                login_user(emp_id, 'employee', permanent=True)
                return redirect('/employee')
            msg = ('Account temporarily locked. Try again later.'
                   if reason == 'locked' else 'Invalid name or PIN.')
            return render_template('employee_login.html', error=msg), 401
        return render_template('employee_login.html', error=None)

    @app.route('/logout', methods=['GET', 'POST'])
    def logout():
        was_manager = session.get('role') == 'manager'
        logout_user()
        return redirect('/login' if was_manager else '/employee/login')
```

- [ ] **Step 3: Create `templates/login.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Manager Login — Ice Line Scheduler</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #f4f5f7; display: flex;
           min-height: 100vh; align-items: center; justify-content: center; margin: 0; }
    .card { background: #fff; padding: 2rem; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.1);
            width: 320px; }
    h1 { font-size: 1.1rem; margin: 0 0 1rem; }
    label { display: block; font-size: .85rem; margin: .75rem 0 .25rem; }
    input { width: 100%; padding: .55rem; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }
    button { width: 100%; margin-top: 1.25rem; padding: .6rem; border: 0; border-radius: 6px;
             background: #2d8cf0; color: #fff; font-size: 1rem; cursor: pointer; }
    .error { color: #c0392b; font-size: .85rem; margin-top: .75rem; }
  </style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <h1>Ice Line Scheduler — Manager Login</h1>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="username" autofocus required>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Log in</button>
  </form>
</body>
</html>
```

- [ ] **Step 4: Create `templates/employee_login.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Employee Login — Ice Line Scheduler</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #f4f5f7; display: flex;
           min-height: 100vh; align-items: center; justify-content: center; margin: 0; }
    .card { background: #fff; padding: 2rem; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.1);
            width: 320px; }
    h1 { font-size: 1.1rem; margin: 0 0 1rem; }
    label { display: block; font-size: .85rem; margin: .75rem 0 .25rem; }
    input { width: 100%; padding: .55rem; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }
    button { width: 100%; margin-top: 1.25rem; padding: .6rem; border: 0; border-radius: 6px;
             background: #19be6b; color: #fff; font-size: 1rem; cursor: pointer; }
    .error { color: #c0392b; font-size: .85rem; margin-top: .75rem; }
  </style>
</head>
<body>
  <form class="card" method="POST" action="/employee/login">
    <h1>Ice Line Schedule — Employee Login</h1>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <label for="name">Your name</label>
    <input id="name" name="name" autocomplete="username" autofocus required>
    <label for="pin">4-digit PIN</label>
    <input id="pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]*"
           maxlength="4" autocomplete="current-password" required>
    <button type="submit">Log in</button>
  </form>
</body>
</html>
```

- [ ] **Step 5: Verify login end-to-end (flag ON)**

```bash
cp schedule.db /tmp/schedule.db.bak
printf 'testpass123\ntestpass123\n' | ./venv/bin/flask --app app.py set-manager-password bob
printf '4321\n' | ./venv/bin/flask --app app.py set-employee-pin ava
AUTH_ENABLED=true ./venv/bin/python app.py >/tmp/auth_t5.log 2>&1 &
sleep 3
echo "-- anon hits / -> 302 to /login --"
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://127.0.0.1:5001/
echo "-- bad manager login -> 401 --"
curl -s -o /dev/null -w "%{http_code}\n" -X POST -d 'username=bob&password=wrong' http://127.0.0.1:5001/login
echo "-- good manager login -> 302, then / -> 200 --"
curl -s -c /tmp/mgr.txt -o /dev/null -w "login=%{http_code}\n" -X POST -d 'username=bob&password=testpass123' http://127.0.0.1:5001/login
curl -s -b /tmp/mgr.txt -o /dev/null -w "home=%{http_code}\n" http://127.0.0.1:5001/
echo "-- employee login then /employee -> 200, but / (manager) -> 302 --"
curl -s -c /tmp/emp.txt -o /dev/null -w "elogin=%{http_code}\n" -X POST -d 'name=ava&pin=4321' http://127.0.0.1:5001/employee/login
curl -s -b /tmp/emp.txt -o /dev/null -w "eportal=%{http_code}\n" http://127.0.0.1:5001/employee
curl -s -b /tmp/emp.txt -o /dev/null -w "emp_hits_manager=%{http_code}\n" http://127.0.0.1:5001/
kill %1 2>/dev/null
```
Expected: anon `/` → `302`; bad login → `401`; good login → `login=302`, `home=200`; employee → `elogin=302`, `eportal=200`, `emp_hits_manager=302` (employee can't reach the manager page — but note `/` has no decorator yet in this task, so `emp_hits_manager` will be `200` until Task 6; that's expected here).

> NOTE: `/` and the API routes are NOT yet decorated in this task — only the login plumbing exists. Full gating lands in Task 6. The anon-`/`→302 line above will only hold once Task 6 is done; in *this* task expect `/` to still return 200. Treat Step 5 as confirming login/logout + session cookies work, not full gating.

- [ ] **Step 6: Commit**

```bash
git add app.py templates/login.html templates/employee_login.html
git commit -m "Auth: add manager/employee login + logout routes and templates"
```

---

## Task 6: Apply protection decorators to existing routes

**Files:**
- Modify: `app.py` — add one decorator line above each protected route's function. **Do not change any route body.**

**Interfaces:**
- Consumes: `manager_required`, `employee_required` (imported in Task 5).

The decorator goes **below** `@app.route(...)` and **above** the `def`. Apply exactly this map:

**`@manager_required`** on: `index` (`/`), `save_schedule` (`POST /api/schedule/<week_start>`), the shift route (`POST /api/schedule/<week_start>/shift`), `GET /api/employees`, `POST /api/employees`, `PUT /api/employees/<id>`, `DELETE /api/employees/<id>`, `POST /api/employees/<id>/restore`, both `/api/notes/...` routes (GET + POST), `GET /api/schedule/<week_start>/export`, `GET /api/schedule/<week_start>/export-pdf`, `GET /api/timeoff-calendars`, `GET /api/backup/export`, `POST /api/backup/import`.

**`@employee_required`** on: `employee_portal` (`/employee`), `GET /api/current-week`, `GET /api/schedule/<week_start>` (the GET one only — the POST stays manager-only).

- [ ] **Step 1: Decorate the manager-only page route**

```python
    @app.route('/')
    @manager_required
    def index():
```

- [ ] **Step 2: Decorate the employee-readable routes**

```python
    @app.route('/employee')
    @app.route('/employee/')
    @employee_required
    def employee_portal():
```
```python
    @app.route('/api/current-week', methods=['GET'])
    @employee_required
    def get_current_week():
```
```python
    @app.route('/api/schedule/<week_start>', methods=['GET'])
    @employee_required
    def get_schedule(week_start):
```
(Use the actual function names as they appear in `app.py`; the decorator line goes directly above `def`.)

- [ ] **Step 3: Decorate every manager-only API route**

Add `@manager_required` directly above the `def` for each of: the `POST /api/schedule/<week_start>` handler, the `/shift` handler, `GET`/`POST` `/api/employees`, the `<int:emp_id>` PUT/DELETE/restore handlers, both `/api/notes/<week_start>/<int:emp_id>` handlers, the Excel `export`, the `export-pdf`, the `timeoff-calendars`, the `backup export`, and the `backup import`. Example shape:

```python
    @app.route('/api/schedule/<week_start>', methods=['POST'])
    @manager_required
    def save_schedule(week_start):
```

**Exact function names** (decorator goes directly above each `def`):
- `@manager_required`: `index`, `save_schedule`, `update_shift`, `get_employees`, `add_employee`, `update_employee`, `delete_employee`, `restore_employee`, `get_note`, `save_note`, `export_schedule`, `export_schedule_pdf`, `export_timeoff_calendars`, `export_database`, `import_database`.
- `@employee_required`: `employee_portal`, `get_current_week`, `get_schedule`.

Verify you covered all of them:
```bash
grep -n "@app.route\|@manager_required\|@employee_required" app.py
```
Every `@app.route` line in the list above must be immediately followed (after any stacked route lines) by exactly one auth decorator. The only routes WITHOUT an auth decorator should be: `/login`, `/employee/login`, `/logout`.

- [ ] **Step 4: Verify full gating (flag ON) + that flag OFF is unchanged**

```bash
cp schedule.db /tmp/schedule.db.bak
printf 'testpass123\ntestpass123\n' | ./venv/bin/flask --app app.py set-manager-password bob
printf '4321\n' | ./venv/bin/flask --app app.py set-employee-pin ava

echo "===== FLAG ON ====="
AUTH_ENABLED=true ./venv/bin/python app.py >/tmp/auth_t6.log 2>&1 &
sleep 3
WEEK=$(curl -s -b /tmp/mgr.txt http://127.0.0.1:5001/api/current-week >/dev/null; echo 2026-06-08)
curl -s -c /tmp/mgr.txt -o /dev/null -X POST -d 'username=bob&password=testpass123' http://127.0.0.1:5001/login
curl -s -c /tmp/emp.txt -o /dev/null -X POST -d 'name=ava&pin=4321' http://127.0.0.1:5001/employee/login
echo "anon save -> expect 401:"
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:5001/api/schedule/2026-06-08
echo "employee save -> expect 401:"
curl -s -b /tmp/emp.txt -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:5001/api/schedule/2026-06-08
echo "employee read schedule -> expect 200:"
curl -s -b /tmp/emp.txt -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/api/schedule/2026-06-08
echo "manager reads employees -> expect 200:"
curl -s -b /tmp/mgr.txt -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/api/employees
echo "employee reads employees -> expect 401:"
curl -s -b /tmp/emp.txt -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/api/employees
kill %1 2>/dev/null

echo "===== FLAG OFF (must behave like today) ====="
./venv/bin/python app.py >/tmp/auth_t6off.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "home=%{http_code}\n" http://127.0.0.1:5001/
curl -s -o /dev/null -w "employees=%{http_code}\n" http://127.0.0.1:5001/api/employees
kill %1 2>/dev/null
```
Expected (flag ON): anon save `401`, employee save `401`, employee read schedule `200`, manager employees `200`, employee employees `401`. Expected (flag OFF): `home=200`, `employees=200`.

- [ ] **Step 5: Manual core regression (flag ON), as logged-in manager**

Open `http://127.0.0.1:5001/login` in a browser (with `AUTH_ENABLED=true ./venv/bin/python app.py` running), log in as `bob` / `testpass123`, then confirm the scheduler is fully functional: create/select a week, edit a shift and confirm autosave, undo/redo, copy previous week, add then delete then restore an employee, edit office hours + special events and save, run Excel export, run PDF export (Chromium path). All must work exactly as before. Stop the app when done.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "Auth: gate scheduler + admin routes (manager), portal + reads (employee)"
```

---

## Task 7: Minimal manager admin — set employee username + PIN

**Files:**
- Modify: `app.py` — add `POST /api/employees/<int:emp_id>/credentials` (manager-only).
- Modify: `static/js/main.js` — add a `setEmployeePin(empId, name)` action and a button in the employee-row actions.

**Interfaces:**
- Consumes: `auth.set_pin`; `get_db()`; `manager_required`.
- Produces: `POST /api/employees/<int:emp_id>/credentials` accepting JSON `{username?, pin?}`.

- [ ] **Step 1: Add the credentials endpoint**

Near the other `/api/employees` routes in `register_routes`, add:

```python
    @app.route('/api/employees/<int:emp_id>/credentials', methods=['POST'])
    @manager_required
    def set_employee_credentials(emp_id):
        """Manager sets/resets an employee's login username and/or 4-digit PIN."""
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip().lower() or None
        pin = data.get('pin')
        conn = get_db()
        try:
            if username:
                conn.execute("UPDATE employees SET username = ? WHERE id = ?", (username, emp_id))
            if pin:
                from auth import set_pin
                set_pin(conn, emp_id, str(pin))
            conn.commit()
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except sqlite3.IntegrityError:
            return jsonify({'error': 'That username is already taken'}), 409
        return jsonify({'success': True})
```

- [ ] **Step 2: Add a minimal UI action in `main.js`**

Add this function near the other employee actions (e.g., next to `exportTimeOffCalendars`):

```javascript
async function setEmployeePin(empId, name) {
    const username = prompt(`Login username for ${name} (lowercase, no spaces). Leave blank to keep current:`);
    if (username === null) return;  // cancelled
    const pin = prompt(`New 4-digit PIN for ${name} (leave blank to keep current):`);
    if (pin === null) return;
    const body = {};
    if (username.trim()) body.username = username.trim();
    if (pin.trim()) body.pin = pin.trim();
    if (!Object.keys(body).length) return;
    const res = await fetch(`${Config.API_BASE}/api/employees/${empId}/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (res.ok) {
        alert(`Login updated for ${name}.`);
    } else {
        const err = await res.json().catch(() => ({}));
        alert(`Could not update login: ${err.error || res.status}`);
    }
}
```

In the employee-row action markup (where `employee-actions` buttons are rendered in `renderToolbar`/row rendering — find the existing per-employee action buttons), add a button:

```javascript
                <button class="employee-action" title="Set login PIN"
                        onclick="setEmployeePin(${employee.id}, '${employee.name.replace(/'/g, "\\'")}')">🔑</button>
```

(Match the surrounding markup/quoting style; place it alongside the existing per-employee action buttons.)

- [ ] **Step 3: Verify the endpoint**

```bash
cp schedule.db /tmp/schedule.db.bak
printf 'testpass123\ntestpass123\n' | ./venv/bin/flask --app app.py set-manager-password bob
AUTH_ENABLED=true ./venv/bin/python app.py >/tmp/auth_t7.log 2>&1 &
sleep 3
curl -s -c /tmp/mgr.txt -o /dev/null -X POST -d 'username=bob&password=testpass123' http://127.0.0.1:5001/login
# find an employee id
EID=$(curl -s -b /tmp/mgr.txt http://127.0.0.1:5001/api/employees | ./venv/bin/python -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
echo "set creds -> expect success:"
curl -s -b /tmp/mgr.txt -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' -d "{\"username\":\"testuser1\",\"pin\":\"5678\"}" http://127.0.0.1:5001/api/employees/$EID/credentials
echo "bad pin -> expect 400:"
curl -s -b /tmp/mgr.txt -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' -d "{\"pin\":\"12\"}" http://127.0.0.1:5001/api/employees/$EID/credentials
echo "anon -> expect 401:"
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' -d "{\"pin\":\"5678\"}" http://127.0.0.1:5001/api/employees/$EID/credentials
# confirm the new creds work for employee login
curl -s -o /dev/null -w "newlogin=%{http_code}\n" -X POST -d 'name=testuser1&pin=5678' http://127.0.0.1:5001/employee/login
kill %1 2>/dev/null
node --check static/js/main.js && echo "main.js OK"
```
Expected: set creds `200`, bad pin `400`, anon `401`, `newlogin=302`, `main.js OK`.

- [ ] **Step 4: Commit**

```bash
git add app.py static/js/main.js
git commit -m "Auth: manager admin endpoint + UI to set employee login PIN"
```

---

## Final verification

- [ ] With `AUTH_ENABLED=false`, the full app behaves exactly as before (manager scheduler + employee portal both fully usable, no login required).
- [ ] With `AUTH_ENABLED=true`: anon is redirected to login from pages and 401'd from APIs; manager login unlocks the scheduler and all admin APIs; employee login unlocks only the portal + schedule reads; 5 bad attempts locks an account for 15 minutes.
- [ ] The full manager core-regression checklist (Task 6 Step 5) passes with auth ON.
- [ ] Rollback rehearsal: flip `AUTH_ENABLED` back to false, restart, confirm normal operation.
