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
  last_login_failure_at TIMESTAMPTZ NULL,
  pwa_installed_at TEXT NULL   -- first time consultant opened the installed PWA (/pwa-ping); ISO string to match db_setup.py + app.py
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
  total NUMERIC(10,2) NULL,             -- discounted subtotal for MPA-placed orders; InTouch total after nightly import (source of truth)
  source TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  discount_amount NUMERIC(10,2) NULL,   -- flat $ off the whole order (item-level mentions summed)
  tax_amount NUMERIC(10,2) NULL,        -- computed $ tax stored at queue time
  discount_type TEXT NULL,              -- what the consultant SAID: '$' or '%' (submitted to InTouch as $ either way)
  discount_value NUMERIC(10,2) NULL,    -- the number she said (20 for "20% off", 5 for "$5 off")
  tax_percent NUMERIC(5,2) NULL         -- rate applied at order time (consultants.tax_rate may change later)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id, order_date DESC);
CREATE INDEX IF NOT EXISTS idx_orders_consultant ON orders(consultant_id, order_date DESC);

-- discount feature (2026-07-18): columns for DBs created before this file carried
-- them. discount_amount / tax_amount / consultants.tax_rate were hand-ALTERed into
-- prod long ago but missing here (fresh-install gap); discount_type / discount_value
-- / tax_percent are new and need the ALTERs run against prod at deploy.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(10,2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax_amount NUMERIC(10,2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_type TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_value NUMERIC(10,2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax_percent NUMERIC(5,2);
ALTER TABLE consultants ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5,2);

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

CREATE TABLE IF NOT EXISTS pcp_lookbook_followups (
  id            BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  customer_id   BIGINT NOT NULL,
  quarter       TEXT   NOT NULL,
  completed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(customer_id, consultant_id, quarter)
);
CREATE INDEX IF NOT EXISTS idx_pcp_lookbook_followups_consultant ON pcp_lookbook_followups(consultant_id, quarter);

CREATE TABLE IF NOT EXISTS inventory_intouch_imports (
  id BIGSERIAL PRIMARY KEY,
  consultant_id BIGINT NOT NULL,
  order_no TEXT NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (consultant_id, order_no)
);

CREATE TABLE IF NOT EXISTS pcp_enrollments (
  id            BIGSERIAL PRIMARY KEY,
  consultant_id INTEGER NOT NULL,
  customer_id   INTEGER,
  pcp_name      TEXT    NOT NULL,
  quarter       TEXT    NOT NULL,
  enrolled      BOOLEAN NOT NULL,
  scraped_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (consultant_id, pcp_name, quarter)
);

CREATE INDEX IF NOT EXISTS idx_pcp_enrollments_consultant ON pcp_enrollments(consultant_id, quarter);

-- secondary InTouch account IDs for duplicate customer handling
ALTER TABLE customers ADD COLUMN IF NOT EXISTS intouch_account_ids TEXT DEFAULT '[]';

-- PWA install tracking (/pwa-ping). Was in db_setup.py (SQLite) but never in
-- prod Postgres → the ping silently failed for everyone (2026-07-15). Migrates
-- existing DBs; also in the consultants CREATE above for fresh ones.
ALTER TABLE consultants ADD COLUMN IF NOT EXISTS pwa_installed_at TEXT;

CREATE TABLE IF NOT EXISTS guest_orders (
  id                    BIGSERIAL PRIMARY KEY,
  consultant_id         INTEGER   NOT NULL,
  intouch_order_id      TEXT      NOT NULL,
  intouch_account_id    TEXT,
  first_name            TEXT,
  last_name             TEXT,
  order_date            TEXT,
  total                 NUMERIC(10,2),
  source                TEXT,
  fulfillment           TEXT,
  items_json            TEXT,
  billing_address_json  TEXT,
  mailing_address_json  TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (consultant_id, intouch_order_id)
);

CREATE TABLE IF NOT EXISTS unit_member_activity_history (
  id                    BIGSERIAL PRIMARY KEY,
  consultant_id         INTEGER       NOT NULL,
  consultant_number     TEXT          NOT NULL,
  period_month          TEXT          NOT NULL,
  activity_status       TEXT,
  last_order_retail     NUMERIC(10,2),
  last_order_wholesale  NUMERIC(10,2),
  career_level_code     TEXT,
  career_level_desc     TEXT,
  myshop_active         INTEGER,
  last_activated_date   DATE,
  synced_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  UNIQUE (consultant_id, consultant_number, period_month)
);
CREATE INDEX IF NOT EXISTS idx_unit_activity_history_consultant ON unit_member_activity_history(consultant_id);
CREATE INDEX IF NOT EXISTS idx_unit_activity_history_period ON unit_member_activity_history(consultant_id, period_month);

-- push_subscriptions (web push / PWA notifications, 2026-07-12)
-- consultant_id from day one: admin-only today, consultant reorder-reminder
-- push is on the roadmap — future feature is UI+copy, not schema surgery.
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id            BIGSERIAL PRIMARY KEY,
  consultant_id INTEGER     NOT NULL,
  endpoint      TEXT        NOT NULL UNIQUE,
  p256dh        TEXT        NOT NULL,
  auth          TEXT        NOT NULL,
  user_agent    TEXT        DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  failed_count  INTEGER     NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_push_subs_consultant ON push_subscriptions(consultant_id);
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