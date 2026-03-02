from db import tx

CONSULTANT_EMAIL = "akrause.marykay@gmail.com"

def row_to_dict(r):
    return {k: r[k] for k in r.keys()}

with tx() as (conn, cur):

    # 1️⃣ Get consultant_id from email
    cur.execute("""
        SELECT id, email
        FROM consultants
        WHERE LOWER(email) = LOWER(?)
    """, (CONSULTANT_EMAIL,))
    consultant = cur.fetchone()

    if not consultant:
        print("Consultant not found.")
        exit()

    consultant_id = consultant["id"]
    print(f"\nConsultant ID: {consultant_id}")
    print(f"Email: {consultant['email']}")

    # 2️⃣ Get customers for that consultant
    cur.execute("""
        SELECT id, first_name, last_name, email, phone, city, state
        FROM customers
        WHERE consultant_id = ?
        ORDER BY last_name, first_name
    """, (consultant_id,))

    customers = cur.fetchall()

    print(f"\nTotal Customers: {len(customers)}\n")

    for c in customers:
        d = row_to_dict(c)
        full_name = f"{d.get('first_name','')} {d.get('last_name','')}".strip()
        print(f"ID {d['id']} — {full_name}")
        print(f"   Email: {d.get('email') or '—'}")
        print(f"   Phone: {d.get('phone') or '—'}")
        print(f"   Location: {d.get('city') or ''} {d.get('state') or ''}".strip())
        print()