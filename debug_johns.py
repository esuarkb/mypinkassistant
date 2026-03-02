from db import tx

CONSULTANT_ID = 1  # change if needed

with tx() as (conn, cur):
    cur.execute("""
        SELECT id, consultant_id, first_name, last_name, phone, email, street, city, state, postal_code
        FROM customers
        WHERE consultant_id = ?
          AND LOWER(first_name) = 'john'
        ORDER BY id DESC
    """, (CONSULTANT_ID,))
    rows = cur.fetchall()

print(f"\nFound {len(rows)} Johns for consultant_id={CONSULTANT_ID}:\n")
for r in rows:
    d = {k: r[k] for k in r.keys()}
    print(d)