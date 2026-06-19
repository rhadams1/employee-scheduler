"""Authentication helpers for the Ice Line scheduler.

Pure of any import from app.py (avoids circular imports). DB-touching functions
take an explicit sqlite3 connection (row_factory=sqlite3.Row); decorators/session
helpers (added in a later task) use only flask.session.
"""
from datetime import datetime, timedelta
from functools import wraps

from flask import current_app, redirect, request, session
from werkzeug.security import generate_password_hash, check_password_hash


def set_password(conn, emp_id, password):
    """Set a manager password and promote the row to role='manager'.

    Also clears any lockout state — an admin setting/resetting a credential
    unlocks the account (the spec's "reset a locked account" behavior).
    """
    if not password:
        raise ValueError("password must not be empty")
    conn.execute(
        "UPDATE employees SET password_hash = ?, role = 'manager', "
        "failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (generate_password_hash(password), emp_id),
    )
    conn.commit()


def set_pin(conn, emp_id, pin):
    """Set a 4-digit employee PIN (hashed). Also clears any lockout state."""
    if not (isinstance(pin, str) and pin.isdigit() and len(pin) == 4):
        raise ValueError("PIN must be exactly 4 digits")
    conn.execute(
        "UPDATE employees SET pin_hash = ?, failed_attempts = 0, "
        "locked_until = NULL WHERE id = ?",
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
