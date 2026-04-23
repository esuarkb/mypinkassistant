# db.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# Optional Postgres dependency (psycopg v3)
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None  # type: ignore


BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "data" / "mk.db"


def is_postgres() -> bool:
    url = (os.environ.get("DATABASE_URL") or "").strip().lower()
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _sqlite_conn() -> sqlite3.Connection:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SQLITE_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# db.py (add near other helpers)

from typing import Optional

def get_system_setting(key: str, default: str = "") -> str:
    """
    Read a setting from system_settings (works for sqlite + postgres).
    """
    key = (key or "").strip()
    if not key:
        return default

    conn = connect()
    cur = conn.cursor()
    try:
        ph = "%s" if is_postgres() else "?"
        cur.execute(f"SELECT value FROM system_settings WHERE key={ph}", (key,))
        row = cur.fetchone()
        if not row:
            return default

        # row might be dict-like (pg) or tuple (sqlite)
        try:
            val = row.get("value")  # type: ignore
        except Exception:
            val = row[0]
        return (val or default)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def set_system_setting(key: str, value: str) -> None:
    """
    Upsert a setting into system_settings (works for sqlite + postgres).
    """
    key = (key or "").strip()
    if not key:
        return

    val = "" if value is None else str(value)

    conn = connect()
    cur = conn.cursor()
    try:
        ph = "%s" if is_postgres() else "?"

        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO system_settings (key, value)
                VALUES ({ph}, {ph})
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
                """,
                (key, val),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO system_settings (key, value)
                VALUES ({ph}, {ph})
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, val),
            )

        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def _pg_conn():
    if psycopg is None:
        raise RuntimeError(
            "Postgres requested (DATABASE_URL is set) but psycopg is not installed. "
            "Add 'psycopg[binary]' to requirements."
        )
    url = os.environ["DATABASE_URL"]
    # autocommit=False: keep transaction control consistent with sqlite
    return psycopg.connect(url, autocommit=False)


def now_sql() -> str:
    """SQL expression for 'now'."""
    return "NOW()" if is_postgres() else "datetime('now')"


def paramify(sql: str) -> str:
    """
    Convert SQLite-style '?' params into Postgres '%s' params when needed.
    This lets you keep most of your existing queries for now.

    NOTE: This is a simple conversion; avoid using literal '?' in SQL strings.
    """
    if is_postgres():
        return sql.replace("?", "%s")
    return sql


def connect():
    """Return a DB-API connection (sqlite3.Connection or psycopg.Connection)."""
    return _pg_conn() if is_postgres() else _sqlite_conn()


@contextmanager
def tx():
    """
    Transaction context manager.
    Usage:
        with tx() as (conn, cur):
            cur.execute(...)
    Commits on success, rollbacks on exception.
    """
    conn = connect()
    cur = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def execute(sql: str, params: Optional[Sequence[Any]] = None) -> None:
    with tx() as (_conn, cur):
        cur.execute(paramify(sql), params or [])


def fetchone(sql: str, params: Optional[Sequence[Any]] = None) -> Optional[dict]:
    with tx() as (_conn, cur):
        cur.execute(paramify(sql), params or [])
        row = cur.fetchone()
        if row is None:
            return None
        # sqlite Row -> dict; psycopg dict_row already dict-like
        return dict(row)


def fetchall(sql: str, params: Optional[Sequence[Any]] = None) -> list[dict]:
    with tx() as (_conn, cur):
        cur.execute(paramify(sql), params or [])
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]


def run_migrations() -> None:
    """Apply any pending schema changes. Safe to call on every startup."""
    conn = connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE customers ADD COLUMN intouch_account_id TEXT")
            conn.commit()
            print("[Migration] Added intouch_account_id to customers")
        except Exception:
            conn.rollback()
    finally:
        conn.close()


def execscript(sql: str) -> None:
    """
    Run a multi-statement script.
    - Works well for SQLite.
    - For Postgres, you should usually run migrations properly; but this can
      still work for simple statements separated by semicolons.
    """
    with tx() as (_conn, cur):
        if not is_postgres():
            # sqlite supports executescript
            _conn.executescript(sql)  # type: ignore[attr-defined]
        else:
            # psycopg does not have executescript; do a naive split
            parts = [p.strip() for p in sql.split(";") if p.strip()]
            for p in parts:
                cur.execute(p)
