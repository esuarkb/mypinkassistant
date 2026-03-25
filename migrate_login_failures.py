# migrate_login_failures.py
#
# One-time migration: adds consecutive_login_failures and
# last_login_failure_at columns to the consultants table.
# Safe to run multiple times.

from dotenv import load_dotenv
load_dotenv()

from db import connect, is_postgres

conn = connect()
cur = conn.cursor()

try:
    if is_postgres():
        cur.execute("""
            ALTER TABLE consultants
            ADD COLUMN IF NOT EXISTS consecutive_login_failures INT NOT NULL DEFAULT 0
        """)
        cur.execute("""
            ALTER TABLE consultants
            ADD COLUMN IF NOT EXISTS last_login_failure_at TIMESTAMPTZ NULL
        """)
    else:
        # SQLite doesn't support IF NOT EXISTS on ALTER TABLE —
        # wrap each in try/except so re-runs are safe
        for sql in [
            "ALTER TABLE consultants ADD COLUMN consecutive_login_failures INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE consultants ADD COLUMN last_login_failure_at TEXT NULL",
        ]:
            try:
                cur.execute(sql)
            except Exception:
                pass  # column already exists

    conn.commit()
    print("✅ Migration complete.")

finally:
    conn.close()
