from db import connect
from inventory_store import (
    upsert_inventory_quantity,
    get_inventory_item,
    list_inventory,
)

conn = connect()
cur = conn.cursor()

try:
    # Add test data
    upsert_inventory_quantity(
        cur,
        consultant_id=1,
        sku="TEST-SKU-123",
        qty_delta=2,
    )

    conn.commit()

    # Get one item
    item = get_inventory_item(cur, consultant_id=1, sku="TEST-SKU-123")
    print("Single item:", item)

    # List all inventory
    all_items = list_inventory(cur, consultant_id=1)
    print("All inventory:", all_items)

finally:
    cur.close()
    conn.close()