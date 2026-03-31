"""
Check for duplicate SKUs in inventory for a given consultant.
Run: python check_inventory_dupes.py <consultant_id>
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from db import connect

consultant_id = int(sys.argv[1]) if len(sys.argv) > 1 else 27

conn = connect()
cur = conn.cursor()

cur.execute("""
    SELECT sku, COUNT(*) as cnt, SUM(qty_on_hand) as total_qty
    FROM inventory
    WHERE consultant_id = %s
    GROUP BY sku
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC
""", (consultant_id,))

rows = cur.fetchall()

cur.execute("SELECT COUNT(*) FROM inventory WHERE consultant_id = %s", (consultant_id,))
total = cur.fetchone()
conn.close()

total_count = total[0] if not isinstance(total, dict) else total["count"]
print(f"\nTotal inventory rows for consultant {consultant_id}: {total_count}")
print(f"Duplicate SKUs: {len(rows)}\n")

if rows:
    print(f"{'SKU':<20} {'Row Count':<12} {'Total Qty'}")
    print("-" * 45)
    for row in rows:
        if isinstance(row, dict):
            sku, cnt, qty = row["sku"], row["cnt"], row["total_qty"]
        else:
            sku, cnt, qty = row
        print(f"{sku:<20} {cnt:<12} {qty}")
else:
    print("No duplicate SKUs found.")
