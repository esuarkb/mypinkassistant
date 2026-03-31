"""
Shows all consultants and their total inventory item count and quantity.
Run in Render shell: python check_inventory.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from db import connect

conn = connect()
cur = conn.cursor()

cur.execute("""
    SELECT c.id, c.first_name, c.last_name, c.email,
           COUNT(i.id) AS sku_count,
           COALESCE(SUM(i.qty_on_hand), 0) AS total_qty
    FROM consultants c
    LEFT JOIN inventory i ON i.consultant_id = c.id
    WHERE c.billing_status IN ('active', 'trialing')
    GROUP BY c.id, c.first_name, c.last_name, c.email
    ORDER BY sku_count DESC
""")

rows = cur.fetchall()
conn.close()

print(f"\n{'ID':<6} {'Name':<25} {'Email':<35} {'SKUs':<6} {'Total Qty'}")
print("-" * 85)
for row in rows:
    if isinstance(row, dict):
        cid, first, last, email, skus, qty = row["id"], row["first_name"], row["last_name"], row["email"], row["sku_count"], row["total_qty"]
    else:
        cid, first, last, email, skus, qty = row

    name = f"{first or ''} {last or ''}".strip()
    print(f"{cid:<6} {name:<25} {email:<35} {skus:<6} {qty}")

print(f"\nTotal consultants: {len(rows)}")
