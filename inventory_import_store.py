# inventory_import_store.py
#
# Tracks which InTouch Cosmetic order numbers have already been imported
# into a consultant's personal inventory, to prevent double-importing.
# Also stores the raw line items per order in inventory_order_items so the
# inventory table can be audited or rebuilt without re-running Playwright.

from __future__ import annotations

from db import connect, is_postgres

PH = "%s" if is_postgres() else "?"


def ensure_import_table() -> None:
    """Create the inventory_intouch_imports table if it doesn't exist, and run
    column migrations for existing tables (order_type, consumer_order_id)."""
    conn = connect()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_intouch_imports (
                    id SERIAL PRIMARY KEY,
                    consultant_id INTEGER NOT NULL,
                    order_no TEXT NOT NULL,
                    order_type TEXT NOT NULL DEFAULT '',
                    consumer_order_id TEXT NOT NULL DEFAULT '',
                    imported_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (consultant_id, order_no)
                )
            """)
            # Migrate existing tables that pre-date these columns
            for col, definition in [
                ("order_type", "TEXT NOT NULL DEFAULT ''"),
                ("consumer_order_id", "TEXT NOT NULL DEFAULT ''"),
            ]:
                cur.execute(f"""
                    ALTER TABLE inventory_intouch_imports
                    ADD COLUMN IF NOT EXISTS {col} {definition}
                """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_intouch_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    consultant_id INTEGER NOT NULL,
                    order_no TEXT NOT NULL,
                    order_type TEXT NOT NULL DEFAULT '',
                    consumer_order_id TEXT NOT NULL DEFAULT '',
                    imported_at TEXT DEFAULT (datetime('now')),
                    UNIQUE (consultant_id, order_no)
                )
            """)
            # SQLite: add columns if missing (ignore error if already present)
            existing = {row[1] for row in cur.execute("PRAGMA table_info(inventory_intouch_imports)")}
            for col, definition in [
                ("order_type", "TEXT NOT NULL DEFAULT ''"),
                ("consumer_order_id", "TEXT NOT NULL DEFAULT ''"),
            ]:
                if col not in existing:
                    cur.execute(f"ALTER TABLE inventory_intouch_imports ADD COLUMN {col} {definition}")
        conn.commit()
    finally:
        conn.close()


def ensure_order_items_table() -> None:
    """Create the inventory_order_items table if it doesn't exist."""
    conn = connect()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_order_items (
                    id SERIAL PRIMARY KEY,
                    consultant_id INTEGER NOT NULL,
                    order_no TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    imported_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_inv_order_items_consultant
                ON inventory_order_items (consultant_id, order_no)
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    consultant_id INTEGER NOT NULL,
                    order_no TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    imported_at TEXT DEFAULT (datetime('now'))
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_inv_order_items_consultant
                ON inventory_order_items (consultant_id, order_no)
            """)
        conn.commit()
    finally:
        conn.close()


def save_order_items(consultant_id: int, order_no: str, items: list) -> None:
    """Store the raw line items for an imported order.

    items: list of {"sku": str, "qty": int}
    Existing rows for this (consultant_id, order_no) are deleted first so
    re-imports don't create duplicates.
    """
    if not items:
        return
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM inventory_order_items "
            f"WHERE consultant_id = {PH} AND order_no = {PH}",
            (int(consultant_id), order_no),
        )
        cur.executemany(
            f"INSERT INTO inventory_order_items (consultant_id, order_no, sku, qty) "
            f"VALUES ({PH}, {PH}, {PH}, {PH})",
            [(int(consultant_id), order_no, item["sku"], item["qty"]) for item in items],
        )
        conn.commit()
    finally:
        conn.close()


def is_order_imported(consultant_id: int, order_no: str) -> bool:
    """Return True if this order number has already been imported for this consultant."""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM inventory_intouch_imports "
            f"WHERE consultant_id = {PH} AND order_no = {PH} LIMIT 1",
            (int(consultant_id), order_no),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def mark_order_imported(
    consultant_id: int,
    order_no: str,
    order_type: str = "",
    consumer_order_id: str = "",
) -> None:
    """Record an order number as imported so it won't be processed again."""
    conn = connect()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO inventory_intouch_imports
                    (consultant_id, order_no, order_type, consumer_order_id)
                VALUES ({PH}, {PH}, {PH}, {PH})
                ON CONFLICT (consultant_id, order_no) DO NOTHING
                """,
                (int(consultant_id), order_no, order_type, consumer_order_id),
            )
        else:
            cur.execute(
                f"""
                INSERT OR IGNORE INTO inventory_intouch_imports
                    (consultant_id, order_no, order_type, consumer_order_id)
                VALUES ({PH}, {PH}, {PH}, {PH})
                """,
                (int(consultant_id), order_no, order_type, consumer_order_id),
            )
        conn.commit()
    finally:
        conn.close()
