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
        try:
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
        finally:
            conn.close()

    @app.cli.command("set-employee-pin")
    @click.argument("identifier")
    @click.option("--pin", prompt=True, hide_input=True)
    def set_employee_pin(identifier, pin):
        conn = _connect()
        try:
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
        finally:
            conn.close()
