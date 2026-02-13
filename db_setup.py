# db_setup.py
import sqlite3
from pathlib import Path

Path("data").mkdir(exist_ok=True)

conn = sqlite3.connect("data/mk.db")
cur = conn.cursor()

# ---- jobs (existing) ----
cur.execute("""
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consultant_id INTEGER,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    error TEXT DEFAULT ''
)
""")

# ---- consultants (if you already have this table, we only add missing columns) ----
cur.execute("""
CREATE TABLE IF NOT EXISTS consultants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    intouch_username TEXT DEFAULT '',
    intouch_password_enc TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")

# Add created_at if missing (older DBs)
cur.execute("PRAGMA table_info(consultants)")
cols = {r[1] for r in cur.fetchall()}
if "created_at" not in cols:
    cur.execute("ALTER TABLE consultants ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'))")

# ---- password reset table ----
cur.execute("""
CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consultant_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (consultant_id) REFERENCES consultants(id)
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_password_resets_token_hash ON password_resets(token_hash)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_password_resets_consultant ON password_resets(consultant_id)")

conn.commit()
conn.close()

print("✅ SQLite updated at data/mk.db")
