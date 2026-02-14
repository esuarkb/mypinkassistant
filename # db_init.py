# db_init.py
from db import connect


def init_db() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            # --- consultants ---
            cur.execute("""
            CREATE TABLE IF NOT EXISTS consultants (
                id BIGSERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'en',
                intouch_username TEXT NOT NULL DEFAULT '',
                intouch_password_enc TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)

            # --- password resets ---
            cur.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id BIGSERIAL PRIMARY KEY,
                consultant_id BIGINT NOT NULL REFERENCES consultants(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,         -- you store epoch seconds as string
                used_at TEXT NULL,
                created_at TEXT NOT NULL DEFAULT to_char(NOW(), 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            );
            """)
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_password_resets_token_hash
            ON password_resets(token_hash);
            """)

            # --- sessions (chat state) ---
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id BIGINT PRIMARY KEY,
                state_json TEXT NOT NULL DEFAULT '{}',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)

            # --- jobs ---
            cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id BIGSERIAL PRIMARY KEY,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                error TEXT NOT NULL DEFAULT '',
                consultant_id BIGINT REFERENCES consultants(id) ON DELETE SET NULL,
                attempts INT NOT NULL DEFAULT 0,
                claimed_by TEXT,
                claimed_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                status_msg TEXT NOT NULL DEFAULT ''
            );
            """)
            cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_consultant_status
            ON jobs(consultant_id, status, id);
            """)

            # --- consultant locks ---
            cur.execute("""
            CREATE TABLE IF NOT EXISTS consultant_locks (
                consultant_id BIGINT PRIMARY KEY,
                locked_by TEXT NOT NULL,
                locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """)

        conn.commit()
        print("✅ Postgres schema initialized (db_init.py).")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()