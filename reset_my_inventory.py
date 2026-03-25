"""
reset_my_inventory.py

Sets qty_on_hand = 0 for all inventory rows belonging to a consultant,
and clears the import history so orders can be re-imported cleanly.

Usage:
    python reset_my_inventory.py
"""
from dotenv import load_dotenv
load_dotenv()

from db import connect, is_postgres

CONSULTANT_EMAIL = "akrause.marykay@gmail.com"

PH = "%s" if is_postgres() else "?"

conn = connect()
cur = conn.cursor()

try:
    # Look up consultant id
    cur.execute(f"SELECT id FROM consultants WHERE email = {PH}", (CONSULTANT_EMAIL,))
    row = cur.fetchone()
    if not row:
        print(f"No consultant found with email {CONSULTANT_EMAIL!r}")
        exit(1)

    cid = row[0] if not isinstance(row, dict) else row["id"]

    # Zero out all inventory quantities
    cur.execute(
        f"UPDATE inventory SET qty_on_hand = 0 WHERE consultant_id = {PH}",
        (cid,),
    )
    inv_rows = cur.rowcount
    print(f"Reset {inv_rows} inventory row(s) to qty_on_hand=0")

    # Clear import history so the next run re-imports cleanly
    cur.execute(
        f"DELETE FROM inventory_intouch_imports WHERE consultant_id = {PH}",
        (cid,),
    )
    import_rows = cur.rowcount
    print(f"Cleared {import_rows} import history record(s)")

    conn.commit()
    print("Done.")

finally:
    conn.close()
