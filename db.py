# db.py
from __future__ import annotations

import os
import sqlite3
import threading
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


# ---------------------------------------------------------------------------
# Postgres connection pool (2026-08-07)
#
# Why: tx() used to open a brand-new psycopg connection — TCP + TLS + auth —
# and throw it away, and one chat message does that several times over. Once
# /chat moved onto Starlette's threadpool (run_in_threadpool, 2026-08-06) many
# chat requests can be in flight at once on a SINGLE instance, so that churn is
# both a per-message latency cost and what would walk us up toward Postgres'
# max_connections (103, 100 usable) as subscribers grow.
#
# Safety rules this deliberately follows:
#   1. SQLite (local dev) is untouched — pooling is Postgres-only.
#   2. connect() is untouched. Its callers close their own connections
#      (worker.py, billing_routes.py, the sync scripts) and a pooled
#      connection's close() means something different. Only tx(), which owns
#      the full lifecycle, borrows from the pool.
#   3. FAIL-OPEN, always. Missing library, pool won't build, pool won't hand
#      one over in time — tx() opens a direct connection exactly as it does
#      today. Pooling can quietly degrade to current behavior; it can never be
#      worse than it.
#   4. Kill switch: MK_DB_POOL=0 disables pooling without a code deploy.
# ---------------------------------------------------------------------------

_POOL = None
_POOL_LOCK = threading.Lock()
_POOL_UNAVAILABLE = False  # set once if the pool can't be built; stop retrying


def _pool_enabled() -> bool:
    return (os.environ.get("MK_DB_POOL") or "1").strip() not in ("0", "false", "no")


def _env_num(name: str, default):
    try:
        return type(default)(os.environ[name])
    except Exception:
        return default


def _get_pool():
    """Return the shared ConnectionPool, or None to mean 'just connect directly'."""
    global _POOL, _POOL_UNAVAILABLE
    if _POOL_UNAVAILABLE or not _pool_enabled() or not is_postgres():
        return None
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        if _POOL_UNAVAILABLE:
            return None
        try:
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(
                os.environ["DATABASE_URL"],
                # Sized to leave headroom under max_connections=103 for the
                # worker's unpooled connections and a second web instance.
                min_size=_env_num("MK_DB_POOL_MIN", 2),
                max_size=_env_num("MK_DB_POOL_MAX", 20),
                # Never block a request for long — on timeout we fall back to a
                # direct connect, which is exactly what happens today.
                timeout=_env_num("MK_DB_POOL_TIMEOUT", 2.0),
                # Recycle so a long-lived instance can't accumulate stale
                # connections across a Postgres restart or a network blip.
                max_lifetime=_env_num("MK_DB_POOL_LIFETIME", 1800.0),
                max_idle=_env_num("MK_DB_POOL_IDLE", 300.0),
                # Validate on checkout: a connection that died while idle gets
                # discarded and replaced instead of being handed to a request.
                check=ConnectionPool.check_connection,
                kwargs={"autocommit": False},  # match _pg_conn()
                name="mpa",
                open=False,
            )
            pool.open()
            _POOL = pool
        except Exception:
            # Library missing, bad URL, anything — run unpooled forever.
            _POOL_UNAVAILABLE = True
            return None
    return _POOL


def close_pool() -> None:
    """Close the pool on shutdown so its worker threads stop cleanly.

    Without this, psycopg_pool's __del__ tries to join those threads during
    interpreter finalization, which Python 3.13+ refuses. Harmless (it prints
    an ignored exception) but noisy in Render's logs on every restart.
    """
    global _POOL
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
    if pool is not None:
        try:
            pool.close()
        except Exception:
            pass


def pool_stats() -> dict:
    """Pool telemetry for the admin page / diagnostics. Empty dict when unpooled."""
    pool = _get_pool()
    if pool is None:
        return {}
    try:
        return dict(pool.get_stats())
    except Exception:
        return {}


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

    Borrows from the Postgres pool when one is available and returns the
    connection at the end; otherwise opens and closes a direct connection, the
    original behavior. Acquisition happens BEFORE the body so that an
    exception raised by the caller's code can never be mistaken for a pool
    failure and cause the body to run twice.
    """
    pool = _get_pool()
    conn = None
    if pool is not None:
        try:
            conn = pool.getconn()
        except Exception:
            conn = None  # pool busy/broken — fall back to today's path

    pooled = conn is not None
    if conn is None:
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
        if pooled:
            try:
                pool.putconn(conn)
            except Exception:
                # Couldn't hand it back — close it so it can't leak.
                try:
                    conn.close()
                except Exception:
                    pass
        else:
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
