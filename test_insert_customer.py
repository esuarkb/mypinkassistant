from db import tx

with tx() as (conn, cur):
    cur.execute("""
        INSERT INTO customers (consultant_id, first_name, last_name, phone, street, city, state, postal_code)
        VALUES (?,?,?,?,?,?,?,?)
    """, (1, "Jane", "Doe", "5551231234", "444 4th St", "Arab", "Alabama", "35976"))

print("inserted")