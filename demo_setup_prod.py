"""
Demo data setup for Facebook presentation — PRODUCTION Postgres.

Usage:
    python demo_setup_prod.py setup    # back up prod data and load fake data
    python demo_setup_prod.py restore  # restore original data from backup
"""
import sys
import json
import random
import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from pathlib import Path
from dotenv import dotenv_values

BACKUP_PATH   = Path("data/prod_backup_presentation.json")
CONSULTANT_ID = 1

cfg = dotenv_values(".env.production")
DATABASE_URL = cfg["DATABASE_URL"]

def connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

FIRST_NAMES = [
    "Ashley", "Brittany", "Chelsea", "Danielle", "Emily",
    "Faith", "Grace", "Hannah", "Isabella", "Jessica",
    "Kaitlyn", "Lauren", "Madison", "Nicole", "Olivia",
    "Paige", "Rachel", "Savannah", "Taylor", "Victoria",
]
LAST_NAMES = [
    "Anderson", "Baker", "Campbell", "Davis", "Evans",
    "Foster", "Griffin", "Harris", "Johnson", "King",
    "Lewis", "Mitchell", "Nelson", "Parker", "Reynolds",
    "Scott", "Thomas", "Walker", "Young", "Clark",
]
STREETS = [
    "123 Magnolia Ln", "456 Peach Tree Dr", "789 Rosewood Ct",
    "321 Sycamore Ave", "654 Willow Creek Rd", "987 Blossom Way",
    "111 Dogwood Dr", "222 Ivy Hill Ln", "333 Cedar Ridge Rd",
    "444 Maple Grove Ct", "555 Sunflower St", "666 Honeysuckle Ln",
    "777 Bluebonnet Way", "888 Clover Field Dr", "999 Jasmine Ct",
    "101 Primrose Path", "202 Larkspur Ln", "303 Morning Glory Dr",
    "404 Camellia Ct", "505 Azalea Ave",
]
CITIES_STATES = [
    ("Birmingham", "AL"), ("Huntsville", "AL"), ("Mobile", "AL"),
    ("Montgomery", "AL"), ("Tuscaloosa", "AL"), ("Decatur", "AL"),
    ("Florence", "AL"), ("Dothan", "AL"), ("Auburn", "AL"),
    ("Hoover", "AL"),
]
ZIPS = ["35801", "35803", "35816", "36109", "36117", "35401",
        "35630", "36830", "35242", "36303"]
BIRTHDAYS = [
    "03-12", "06-24", "09-05", "01-18", "11-30",
    "04-07", "07-22", "02-14", "08-19", "05-31",
    "10-03", "12-25", "03-28", "06-11", "09-17",
    "01-04", "07-08", "04-21", "11-15", "08-02",
]

ORDER_PRODUCTS = [
    ("10217417", "TimeWise Miracle Set - Normal/Dry", 116.00),
    ("10217415", "TimeWise Miracle Set - Combination/Oily", 116.00),
    ("10171886", "TimeWise Replenishing Serum C+E", 60.00),
    ("10198866", "TimeWise Microdermabrasion Plus Set", 58.00),
    ("10176966", "Mary Kay Gel Mask", 32.00),
    ("10245671", "White Tea & Citrus Satin Hands Pampering Set", 44.00),
    ("10176450", "Mary Kay Ultimate Mascara - Black", 20.00),
    ("10190365", "Mary Kay Unlimited Lip Gloss - Pink Chiffon", 18.00),
    ("10180358", "Mary Kay Lip Liner - Blush", 16.00),
    ("10163626", "TimeWise Age Minimize 3D Eye Cream", 40.00),
    ("10217519", "Mary Kay CC Cream SPF 15 - Light to Medium", 28.00),
    ("10163625", "TimeWise Age Minimize 3D Day Cream SPF 30", 34.00),
    ("10157924", "Mary Kay Micellar Water", 20.00),
    ("10233587", "Clear Proof Acne System Set", 56.00),
    ("10208384", "TimeWise Repair Volu-Firm Day Cream SPF 30", 55.00),
    ("10223245", "Beyond Ultimate TimeWise Miracle Set - C/O", 208.00),
    ("10107305", "Mary Kay Essential Brush Collection", 60.00),
    ("10176452", "Mary Kay Lash Love Mascara - I ♥ Black", 20.00),
    ("10213898", "Mary Kay Satin Hands Pampering Set", 42.00),
    ("10235051", "Mary Kay Confidently You Eau de Parfum", 55.00),
]

INVENTORY_ITEMS = [
    ("10217417", 4), ("10217415", 3), ("10223245", 2),
    ("10171886", 4), ("10198866", 3), ("10245671", 5),
    ("10176966", 4), ("10163626", 4), ("10217519", 5),
    ("10163625", 3), ("10176450", 6), ("10176452", 4),
    ("10190365", 5), ("10180358", 4), ("10107305", 2),
    ("10157924", 6), ("10211954", 2), ("10208384", 3),
    ("10235051", 2), ("10213898", 3),
]


def setup():
    if BACKUP_PATH.exists():
        print(f"Backup already exists at {BACKUP_PATH} — skipping to protect original data.")
        print("Delete it first if you want a fresh backup.")
        return

    conn = connect()
    cur  = conn.cursor()

    # Export current data to JSON backup
    backup = {}
    for table, pk in [
        ("customers",   "consultant_id"),
        ("orders",      "consultant_id"),
        ("inventory",   "consultant_id"),
        ("customer_followups",         "consultant_id"),
        ("customer_birthday_followups","consultant_id"),
        ("pcp_enrollments",            "consultant_id"),
    ]:
        cur.execute(f"SELECT * FROM {table} WHERE consultant_id = %s", (CONSULTANT_ID,))
        backup[table] = [dict(r) for r in cur.fetchall()]

    # Also back up order_items (no consultant_id — join through orders)
    cur.execute("""
        SELECT oi.* FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.consultant_id = %s
    """, (CONSULTANT_ID,))
    backup["order_items"] = [dict(r) for r in cur.fetchall()]

    # Convert any non-serializable types
    def _serial(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)

    BACKUP_PATH.write_text(json.dumps(backup, default=_serial, indent=2))
    print(f"✅ Backed up production data → {BACKUP_PATH}")

    # Wipe consultant 1's data
    cur.execute("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id=%s)", (CONSULTANT_ID,))
    cur.execute("DELETE FROM orders WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_birthday_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM pcp_enrollments WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customers WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory WHERE consultant_id=%s", (CONSULTANT_ID,))

    random.seed(42)
    today = date.today()

    # Insert 20 fake customers
    customer_ids = []
    names = list(zip(FIRST_NAMES, LAST_NAMES))
    random.shuffle(names)
    for i, (first, last) in enumerate(names):
        city, state = random.choice(CITIES_STATES)
        street      = STREETS[i]
        phone_num   = f"256{random.randint(3000000, 9999999)}"
        email       = f"{first.lower()}.{last.lower()}@gmail.com"
        birthday    = BIRTHDAYS[i]
        cur.execute("""
            INSERT INTO customers
              (consultant_id, first_name, last_name, email, phone, street, city, state,
               postal_code, birthday, source_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')
            RETURNING id
        """, (CONSULTANT_ID, first, last, email, phone_num, street, city, state,
              random.choice(ZIPS), birthday))
        customer_ids.append(cur.fetchone()["id"])

    # Insert orders
    products = list(ORDER_PRODUCTS)
    for cid in customer_ids:
        for _ in range(random.randint(1, 2)):
            days_back  = random.randint(14, 400)
            order_date = (today - timedelta(days=days_back)).isoformat()
            items      = random.sample(products, random.randint(2, 3))
            total      = sum(p[2] for p in items)
            cur.execute("""
                INSERT INTO orders (consultant_id, customer_id, order_date, total, source)
                VALUES (%s,%s,%s,%s,'consultant') RETURNING id
            """, (CONSULTANT_ID, cid, order_date, total))
            oid = cur.fetchone()["id"]
            for sku, name, price in items:
                cur.execute("""
                    INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity)
                    VALUES (%s,%s,%s,%s,1)
                """, (oid, sku, name, price))

    # Insert inventory
    for sku, qty in INVENTORY_ITEMS:
        cur.execute("""
            INSERT INTO inventory (consultant_id, sku, qty_on_hand)
            VALUES (%s,%s,%s)
        """, (CONSULTANT_ID, sku, qty))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Inserted 20 demo customers, orders, and inventory into production")
    print(f"\nRun 'python demo_setup_prod.py restore' after the presentation.")


def restore():
    if not BACKUP_PATH.exists():
        print(f"❌ No backup found at {BACKUP_PATH}")
        return

    backup = json.loads(BACKUP_PATH.read_text())
    conn   = connect()
    cur    = conn.cursor()

    # Wipe demo data
    cur.execute("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id=%s)", (CONSULTANT_ID,))
    cur.execute("DELETE FROM orders WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_birthday_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM pcp_enrollments WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customers WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory WHERE consultant_id=%s", (CONSULTANT_ID,))

    def _restore_table(table, rows, skip_id=False):
        if not rows:
            return
        for row in rows:
            if skip_id:
                row.pop("id", None)
            cols = ", ".join(row.keys())
            vals = ", ".join(["%s"] * len(row))
            cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({vals})", list(row.values()))

    _restore_table("customers",                    backup.get("customers", []),    skip_id=False)
    _restore_table("orders",                       backup.get("orders", []),       skip_id=False)
    _restore_table("order_items",                  backup.get("order_items", []),  skip_id=False)
    _restore_table("inventory",                    backup.get("inventory", []),    skip_id=False)
    _restore_table("customer_followups",           backup.get("customer_followups", []),          skip_id=False)
    _restore_table("customer_birthday_followups",  backup.get("customer_birthday_followups", []), skip_id=False)
    _restore_table("pcp_enrollments",              backup.get("pcp_enrollments", []),             skip_id=False)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Production data restored from backup.")
    print(f"You can delete {BACKUP_PATH} now if everything looks good.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "restore":
        restore()
    else:
        print("Usage: python demo_setup_prod.py setup|restore")
