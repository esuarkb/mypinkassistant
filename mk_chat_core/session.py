"""Chat session state — one JSON blob per consultant in the sessions table
(holds the pending flow, last referenced customer, follow-up offset).
"""
import json

from db import is_postgres

from .dbutil import PH, db_connect


def ensure_sessions_table():
    """
    Keep sessions schema compatible across SQLite + Postgres.
    We use session_id (not id) to avoid reserved-word headaches and to match your app usage.
    """
    conn = db_connect()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id BIGINT PRIMARY KEY,
                  state_json TEXT NOT NULL DEFAULT '{}',
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id INTEGER PRIMARY KEY,
                  state_json TEXT NOT NULL DEFAULT '{}',
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def load_session_state(session_id: int = 1) -> dict:
    ensure_sessions_table()
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT state_json FROM sessions WHERE session_id={PH}", (session_id,))
        row = cur.fetchone()

        if not row:
            state = {"last_customer": None, "pending": None}
            cur.execute(
                f"INSERT INTO sessions (session_id, state_json) VALUES ({PH}, {PH})",
                (session_id, json.dumps(state)),
            )
            conn.commit()
            return state

        # row could be tuple (sqlite) or dict-like (psycopg dict_row)
        if isinstance(row, dict):
            return json.loads(row.get("state_json") or "{}")
        return json.loads(row[0])
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def save_session_state(state: dict, session_id: int = 1) -> None:
    ensure_sessions_table()
    conn = db_connect()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                f"UPDATE sessions SET state_json={PH}, updated_at=NOW() WHERE session_id={PH}",
                (json.dumps(state), session_id),
            )
        else:
            cur.execute(
                f"UPDATE sessions SET state_json={PH}, updated_at=CURRENT_TIMESTAMP WHERE session_id={PH}",
                (json.dumps(state), session_id),
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
