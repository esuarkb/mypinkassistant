from db import tx

with tx() as (conn, cur):
    cur.execute("""
        SELECT
          o.id AS order_id,
          o.customer_id,
          c.first_name,
          c.last_name,
          o.total,
          o.order_date
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        ORDER BY o.id DESC
        LIMIT 20
    """)
    rows = cur.fetchall()

print("\nLast 20 orders with customer attached:\n")
for r in rows:
    # sqlite3.Row -> dict-like
    d = {k: r[k] for k in r.keys()}
    print(d)