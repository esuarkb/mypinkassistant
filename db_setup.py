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
if "welcome_email_sent" not in cols:
    cur.execute("ALTER TABLE consultants ADD COLUMN welcome_email_sent INTEGER DEFAULT 0")
if "email_opted_out" not in cols:
    cur.execute("ALTER TABLE consultants ADD COLUMN email_opted_out INTEGER DEFAULT 0")
if "pwa_installed_at" not in cols:
    cur.execute("ALTER TABLE consultants ADD COLUMN pwa_installed_at TEXT")

# Add sync_status to unit_members if missing (tracks terminated/removed consultants)
cur.execute("PRAGMA table_info(unit_members)")
um_cols = {r[1] for r in cur.fetchall()}
if "sync_status" not in um_cols:
    cur.execute("ALTER TABLE unit_members ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'active'")

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

# ---- system settings (used by db.py get_system_setting / set_system_setting) ----
cur.execute("""
CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
)
""")

# ---- customers ----
cur.execute("""
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  email TEXT,
  phone TEXT,
  street TEXT,
  city TEXT,
  state TEXT,
  postal_code TEXT,
  birthday TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_customers_consultant ON customers(consultant_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(consultant_id, last_name, first_name)")

# ---- orders ----
cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL,
  order_date TEXT NOT NULL DEFAULT (datetime('now')),
  total REAL,
  source TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id, order_date DESC)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_consultant ON orders(consultant_id, order_date DESC)")

# ---- order items ----
cur.execute("""
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL,
  sku TEXT NOT NULL,
  product_name TEXT NOT NULL,
  unit_price REAL NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_order_items_sku ON order_items(sku)")

# ---- street2 column (apt/suite) ----
try:
    cur.execute("ALTER TABLE customers ADD COLUMN street2 TEXT")
except Exception:
    pass  # already exists

# ---- tags column ----
try:
    cur.execute("ALTER TABLE customers ADD COLUMN tags TEXT")
except Exception:
    pass  # already exists

# ---- intouch_order_id for deduplication on order history import ----
try:
    cur.execute("ALTER TABLE orders ADD COLUMN intouch_order_id TEXT")
except Exception:
    pass  # already exists

# ---- customer followups (2+2+2) ----
cur.execute("""
CREATE TABLE IF NOT EXISTS customer_followups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  followup_window INTEGER NOT NULL,
  completed_at TEXT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(order_id, followup_window)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_followups_consultant ON customer_followups(consultant_id, completed_at)")

# ---- birthday followups ----
cur.execute("""
CREATE TABLE IF NOT EXISTS customer_birthday_followups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL,
  year INTEGER NOT NULL,
  completed_at TEXT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(customer_id, consultant_id, year)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_birthday_followups_consultant ON customer_birthday_followups(consultant_id, year)")

# ---- pcp enrollments ----
cur.execute("""
CREATE TABLE IF NOT EXISTS pcp_enrollments (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  customer_id   INTEGER,
  pcp_name      TEXT    NOT NULL,
  quarter       TEXT    NOT NULL,
  enrolled      INTEGER NOT NULL,
  scraped_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, pcp_name, quarter)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_pcp_enrollments_consultant ON pcp_enrollments(consultant_id, quarter)")

# ---- pcp lookbook followups ----
cur.execute("""
CREATE TABLE IF NOT EXISTS pcp_lookbook_followups (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  customer_id   INTEGER NOT NULL,
  quarter       TEXT    NOT NULL,
  completed_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(customer_id, consultant_id, quarter)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_pcp_lookbook_followups_consultant ON pcp_lookbook_followups(consultant_id, quarter)")

# ---- intouch_account_ids — secondary InTouch account IDs for duplicate handling ----
try:
    cur.execute("ALTER TABLE customers ADD COLUMN intouch_account_ids TEXT DEFAULT '[]'")
except Exception:
    pass  # already exists

# ---- guest orders (unmatched InTouch orders — not consultant-accessible yet) ----
cur.execute("""
CREATE TABLE IF NOT EXISTS guest_orders (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id         INTEGER NOT NULL,
  intouch_order_id      TEXT    NOT NULL,
  intouch_account_id    TEXT,
  first_name            TEXT,
  last_name             TEXT,
  order_date            TEXT,
  total                 REAL,
  source                TEXT,
  fulfillment           TEXT,
  items_json            TEXT,
  billing_address_json  TEXT,
  mailing_address_json  TEXT,
  created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, intouch_order_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS intent_logs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id INTEGER NOT NULL,
  intent        TEXT    NOT NULL,
  confidence    REAL,
  message_text  TEXT,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_intent_logs_consultant ON intent_logs(consultant_id, created_at)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_intent_logs_intent ON intent_logs(intent, created_at)")
cur.execute("PRAGMA table_info(intent_logs)")
existing = {r[1] for r in cur.fetchall()}
if "response_text" not in existing:
    cur.execute("ALTER TABLE intent_logs ADD COLUMN response_text TEXT")
if "user_agent" not in existing:
    cur.execute("ALTER TABLE intent_logs ADD COLUMN user_agent TEXT")

cur.execute("""
CREATE TABLE IF NOT EXISTS unit_members (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id           INTEGER NOT NULL,
  intouch_contact_id      TEXT    NOT NULL,
  consultant_number       TEXT,
  first_name              TEXT,
  last_name               TEXT,
  email                   TEXT,
  phone                   TEXT,
  address                 TEXT,
  city                    TEXT,
  state                   TEXT,
  zip                     TEXT,
  career_level_code       TEXT,
  career_level_desc       TEXT,
  activity_status         TEXT,
  language                TEXT,
  myshop_active           INTEGER,
  birthday                TEXT,
  start_date              TEXT,
  last_order_date         TEXT,
  last_order_wholesale    REAL,
  last_order_retail       REAL,
  unit_number             TEXT,
  segments                TEXT,
  recruiter_info          TEXT,
  is_personal_recruit     INTEGER NOT NULL DEFAULT 0,
  synced_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, intouch_contact_id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_members_consultant ON unit_members(consultant_id)")

cur.execute("""
CREATE TABLE IF NOT EXISTS unit_great_start (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id           INTEGER NOT NULL,
  consultant_number       TEXT    NOT NULL,
  total_bundles           INTEGER,
  needed_next_bundle      REAL,
  promotion_end_date      TEXT,
  total_production        REAL,
  rsks_bundles            INTEGER,
  rsks_production_left    REAL,
  production_month_key    TEXT,
  synced_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, consultant_number)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_great_start_consultant ON unit_great_start(consultant_id)")

cur.execute("""
CREATE TABLE IF NOT EXISTS unit_star_tracking (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id           INTEGER NOT NULL,
  consultant_number       TEXT    NOT NULL,
  contest_amount          REAL,
  level_achieved          TEXT,
  level_name              TEXT,
  needed_ruby             REAL,
  needed_diamond          REAL,
  needed_emerald          REAL,
  needed_pearl            REAL,
  contest_begin_date      TEXT,
  contest_end_date        TEXT,
  total_star_quarters     INTEGER,
  synced_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, consultant_number)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_star_tracking_consultant ON unit_star_tracking(consultant_id)")

cur.execute("""
CREATE TABLE IF NOT EXISTS unit_rise_radiate (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id           INTEGER NOT NULL,
  intouch_contact_id      TEXT,
  consultant_number       TEXT    NOT NULL,
  contest_goal            REAL,
  amount_needed           REAL,
  challenge_count         INTEGER,
  month0_production       REAL,
  month1_production       REAL,
  month2_production       REAL,
  month3_production       REAL,
  month4_production       REAL,
  month5_production       REAL,
  display_month0          TEXT,
  display_month1          TEXT,
  display_month2          TEXT,
  display_month3          TEXT,
  display_month4          TEXT,
  display_month5          TEXT,
  synced_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, consultant_number)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_rise_radiate_consultant ON unit_rise_radiate(consultant_id)")

cur.execute("""
CREATE TABLE IF NOT EXISTS unit_registrations (
  id                          INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id               INTEGER NOT NULL,
  intouch_contact_id          TEXT,
  consultant_number           TEXT    NOT NULL,
  event_key                   INTEGER NOT NULL,
  event_name                  TEXT,
  event_begin_date            TEXT,
  registered_count            INTEGER DEFAULT 0,
  wait_list_count             INTEGER DEFAULT 0,
  guest_registered_count      INTEGER DEFAULT 0,
  guest_wait_list_count       INTEGER DEFAULT 0,
  registered_status           TEXT,
  synced_at                   TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, consultant_number, event_key)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_registrations_consultant ON unit_registrations(consultant_id)")

cur.execute("""
CREATE TABLE IF NOT EXISTS unit_member_activity_history (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  consultant_id           INTEGER NOT NULL,
  consultant_number       TEXT    NOT NULL,
  period_month            TEXT    NOT NULL,
  activity_status         TEXT,
  last_order_retail       REAL,
  last_order_wholesale    REAL,
  career_level_code       TEXT,
  career_level_desc       TEXT,
  myshop_active           INTEGER,
  last_activated_date     TEXT,
  synced_at               TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consultant_id, consultant_number, period_month)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_activity_history_consultant ON unit_member_activity_history(consultant_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_unit_activity_history_period ON unit_member_activity_history(consultant_id, period_month)")

conn.commit()
conn.close()

print("✅ SQLite updated at data/mk.db")
