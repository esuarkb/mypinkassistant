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

conn.commit()
conn.close()

print("✅ SQLite updated at data/mk.db")
