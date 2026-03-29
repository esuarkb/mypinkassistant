"""
Queues a NEW_CUSTOMER job for every customer belonging to a consultant.
Run locally to re-push customers to MyCustomers after an accidental delete.

Usage:
    python requeue_customers.py <consultant_id>
"""
import sys
sys.path.insert(0, ".")

from db import connect
from mk_chat_core import insert_job, normalize_birthday

def main(consultant_id: int) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT first_name, last_name, email, phone, street, city, state,
               postal_code, birthday
        FROM customers
        WHERE consultant_id = ?
        ORDER BY last_name, first_name
        """,
        (consultant_id,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"No customers found for consultant {consultant_id}.")
        return

    queued = 0
    skipped = 0
    for row in rows:
        first, last, email, phone, street, city, state, postal, birthday = row

        if not first or not last:
            print(f"  Skipping — missing name: {first!r} {last!r}")
            skipped += 1
            continue

        payload = {
            "First Name":  first  or "",
            "Last Name":   last   or "",
            "Email":       email  or "",
            "Phone":       phone  or "",
            "Street":      street or "",
            "City":        city   or "",
            "State":       state  or "",
            "Postal Code": postal or "",
            "Birthday":    normalize_birthday(birthday or ""),
        }

        insert_job("NEW_CUSTOMER", payload, consultant_id=consultant_id)
        print(f"  Queued: {first} {last}")
        queued += 1

    print(f"\nDone — {queued} queued, {skipped} skipped.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python requeue_customers.py <consultant_id>")
        sys.exit(1)
    main(int(sys.argv[1]))
