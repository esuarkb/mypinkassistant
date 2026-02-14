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
