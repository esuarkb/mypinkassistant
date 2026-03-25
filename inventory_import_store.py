# inventory_import_store.py
#
# Tracks which InTouch Cosmetic order numbers have already been imported
# into a consultant's personal inventory, to prevent double-importing.

from __future__ import annotations

from db import connect, is_postgres

PH = "%s" if is_postgres() else "?"


def ensure_import_table() -> None:
    """Create the inventory_intouch_imports table if it doesn't exist."""
    conn = connect()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_intouch_imports (
                    id SERIAL PRIMARY KEY,
                    consultant_id INTEGER NOT NULL,
                    order_no TEXT NOT NULL,
                    imported_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (consultant_id, order_no)
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_intouch_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    consultant_id INTEGER NOT NULL,
                    order_no TEXT NOT NULL,
                    imported_at TEXT DEFAULT (datetime('now')),
                    UNIQUE (consultant_id, order_no)
                )
            """)
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


def mark_order_imported(consultant_id: int, order_no: str) -> None:
    """Record an order number as imported so it won't be processed again."""
    conn = connect()
    try:
        cur = conn.cursor()
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO inventory_intouch_imports (consultant_id, order_no)
                VALUES ({PH}, {PH})
                ON CONFLICT (consultant_id, order_no) DO NOTHING
                """,
                (int(consultant_id), order_no),
            )
        else:
            cur.execute(
                f"""
                INSERT OR IGNORE INTO inventory_intouch_imports (consultant_id, order_no)
                VALUES ({PH}, {PH})
                """,
                (int(consultant_id), order_no),
            )
        conn.commit()
    finally:
        conn.close()
