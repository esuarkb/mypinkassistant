# db_init_pg.py
import os
import psycopg


DDL = """
-- consultants
CREATE TABLE IF NOT EXISTS consultants (
  id BIGSERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  first_name TEXT NOT NULL DEFAULT '',
  last_name TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT 'en',
  intouch_username TEXT NOT NULL DEFAULT '',
  intouch_password_enc TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  consecutive_login_failures INT NOT NULL DEFAULT 0,
  last_login_failure_at TIMESTAMPTZ NULL
);

-- password resets
CREATE TABLE IF NOT EXISTS password_resets (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL REFERENCES consultants(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,         -- epoch seconds as string (matching your current app logic)
  used_at TEXT NULL,
  created_at TEXT NOT NULL DEFAULT to_char(NOW(), 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
);
CREATE INDEX IF NOT EXISTS idx_password_resets_token_hash
ON password_resets(token_hash);

-- sessions (chat state)
CREATE TABLE IF NOT EXISTS sessions (
  session_id BIGINT PRIMARY KEY,
  state_json TEXT NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- jobs
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
CREATE INDEX IF NOT EXISTS idx_jobs_consultant_status
ON jobs(consultant_id, status, id);

-- consultant locks
CREATE TABLE IF NOT EXISTS consultant_locks (
  consultant_id BIGINT PRIMARY KEY,
  locked_by TEXT NOT NULL,
  locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- system settings (used by db.py get_system_setting / set_system_setting)
CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- customers
CREATE TABLE IF NOT EXISTS customers (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  email TEXT NULL,
  phone TEXT NULL,
  street TEXT NULL,
  city TEXT NULL,
  state TEXT NULL,
  postal_code TEXT NULL,
  birthday TEXT NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_consultant ON customers(consultant_id);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(consultant_id, last_name, first_name);

-- orders
CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  order_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  total NUMERIC(10,2) NULL,
  source TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id, order_date DESC);
CREATE INDEX IF NOT EXISTS idx_orders_consultant ON orders(consultant_id, order_date DESC);

-- order items
CREATE TABLE IF NOT EXISTS order_items (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  sku TEXT NOT NULL,
  product_name TEXT NOT NULL,
  unit_price NUMERIC(10,2) NOT NULL,
  quantity INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_sku ON order_items(sku);

-- customer followups (2+2+2)
CREATE TABLE IF NOT EXISTS customer_followups (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  order_id BIGINT NOT NULL,
  followup_window INT NOT NULL,
  completed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(order_id, followup_window)
);
CREATE INDEX IF NOT EXISTS idx_followups_consultant ON customer_followups(consultant_id, completed_at);

-- street2 column (apt/suite)
ALTER TABLE customers ADD COLUMN IF NOT EXISTS street2 TEXT;

-- tags column
ALTER TABLE customers ADD COLUMN IF NOT EXISTS tags TEXT;

-- birthday followups
CREATE TABLE IF NOT EXISTS customer_birthday_followups (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  year INT NOT NULL,
  completed_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(customer_id, consultant_id, year)
);
CREATE INDEX IF NOT EXISTS idx_birthday_followups_consultant ON customer_birthday_followups(consultant_id, year);

CREATE TABLE IF NOT EXISTS inventory_intouch_imports (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  order_no TEXT NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (consultant_id, order_no)
);
"""


def main() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")

    # psycopg requires postgres/postgresql scheme; Render often provides postgres:// which is fine
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

    print("✅ Postgres schema initialized.")


if __name__ == "__main__":
    main()