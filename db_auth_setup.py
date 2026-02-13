import os
import sqlite3
from pathlib import Path
import hashlib
import secrets

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mk.db"

def pbkdf2_hash_password(password: str, salt_hex: str | None = None, iterations: int = 150_000) -> str:
    if salt_hex is None:
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
    else:
        salt = bytes.fromhex(salt_hex)

    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt_hex}${dk.hex()}"

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB not found at {DB_PATH}. Run your existing db_setup.py first.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # consultants table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS consultants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'en',
        intouch_username TEXT DEFAULT '',
        intouch_password_enc TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    # add consultant_id to jobs if missing
    cur.execute("PRAGMA table_info(jobs);")
    cols = [r[1] for r in cur.fetchall()]
    if "consultant_id" not in cols:
        cur.execute("ALTER TABLE jobs ADD COLUMN consultant_id INTEGER;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_consultant_status ON jobs(consultant_id, status, id);")

    conn.commit()

    # If no consultants exist, offer to create the first one
    cur.execute("SELECT COUNT(*) FROM consultants;")
    count = cur.fetchone()[0]

    if count == 0:
        print("\nNo consultants exist yet. Let's create the first login.\n")
        email = input("Consultant email: ").strip().lower()
        pw = input("Consultant password: ").strip()
        ph = pbkdf2_hash_password(pw)

        cur.execute(
            "INSERT INTO consultants (email, password_hash, language) VALUES (?, ?, 'en')",
            (email, ph),
        )
        conn.commit()
        print(f"\n✅ Created consultant account for {email}\n")
    else:
        print(f"✅ DB updated. Consultants already exist: {count}")

    conn.close()

if __name__ == "__main__":
    main()
