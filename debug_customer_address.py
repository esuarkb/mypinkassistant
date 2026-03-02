from db import tx

FIRST = "John"
LAST = "Dorian"

with tx() as (conn, cur):
    cur.execute("""
        SELECT id, first_name, last_name, street, city, state, postal_code, email, phone, birthday
        FROM customers
        WHERE LOWER(first_name) = LOWER(?)
          AND LOWER(last_name) = LOWER(?)
        ORDER BY id DESC
        LIMIT 1
    """, (FIRST, LAST))

    row = cur.fetchone()
    if not row:
        print("No match found.")
    else:
        d = {k: row[k] for k in row.keys()}
        print(d)