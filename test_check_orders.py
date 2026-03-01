from db import tx

def row_to_dict(r):
    # sqlite3.Row supports keys()
    return {k: r[k] for k in r.keys()}

with tx() as (conn, cur):
    cur.execute("""
        SELECT id, consultant_id, customer_id, total, source, order_date, created_at
        FROM orders
        ORDER BY id DESC
        LIMIT 3
    """)
    orders = cur.fetchall()

    print("\nORDERS:")
    for o in orders:
        d = row_to_dict(o)
        print(d)

        cur.execute("""
            SELECT sku, product_name, unit_price, quantity
            FROM order_items
            WHERE order_id = ?
        """, (d["id"],))
        items = cur.fetchall()

        print("  ITEMS:")
        for it in items:
            print("  ", row_to_dict(it))
        print()