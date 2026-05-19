"""
Demo data setup for presentations — PRODUCTION Postgres.

Usage:
    python demo_setup_prod.py setup    # back up prod data and load fake data
    python demo_setup_prod.py restore  # restore original data from backup
"""
import sys
import json
import random
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from pathlib import Path
from dotenv import dotenv_values

BACKUP_PATH   = Path("data/prod_backup_presentation.json")
CONSULTANT_ID = 1

cfg = dotenv_values(".env.production")
DATABASE_URL = cfg["DATABASE_URL"]

def connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

# ── Customer name pool (100 unique combos) ───────────────────────────────────
FIRST_NAMES = [
    "Ashley", "Brittany", "Chelsea", "Danielle", "Emily",
    "Faith", "Grace", "Hannah", "Isabella", "Jessica",
    "Kaitlyn", "Lauren", "Madison", "Nicole", "Olivia",
    "Paige", "Rachel", "Savannah", "Taylor", "Victoria",
    "Amber", "Brooke", "Cassandra", "Diana", "Eleanor",
    "Fiona", "Georgia", "Haley", "Iris", "Julia",
    "Kayla", "Lindsay", "Morgan", "Natalie", "Peyton",
    "Quinn", "Rebecca", "Stephanie", "Tiffany", "Vanessa",
    "Allison", "Bethany", "Courtney", "Delaney", "Eva",
    "Gabrielle", "Heather", "Jade", "Kelsey", "Leah",
    "Megan", "Nadia", "Phoebe", "Renee", "Shelby",
    "Tamara", "Uma", "Wendy", "Ximena", "Yasmine",
    "Zoey", "April", "Brenda", "Carmen", "Dawn",
    "Elaine", "Francesca", "Gloria", "Holly", "Ingrid",
    "Jamie", "Karen", "Lisa", "Maria", "Nancy",
    "Opal", "Patricia", "Rita", "Sandra", "Theresa",
    "Ursula", "Valerie", "Whitney", "Xena", "Yvonne",
    "Zara", "Abigail", "Brianna", "Cecilia", "Daphne",
    "Esther", "Florence", "Gwendolyn", "Helena", "Ilana",
    "Josephine", "Katrina", "Lorraine", "Miriam", "Nina",
]
LAST_NAMES = [
    "Anderson", "Baker", "Campbell", "Davis", "Evans",
    "Foster", "Griffin", "Harris", "Johnson", "King",
    "Lewis", "Mitchell", "Nelson", "Parker", "Reynolds",
    "Scott", "Thomas", "Walker", "Young", "Clark",
    "Adams", "Brown", "Carter", "Dixon", "Edwards",
    "Flynn", "Graham", "Hall", "Ingram", "Jenkins",
    "Knight", "Lane", "Moore", "Nash", "Owen",
    "Price", "Quinn", "Roberts", "Smith", "Turner",
    "Underwood", "Vaughn", "Warren", "Xavier", "York",
    "Zimmerman", "Allen", "Brooks", "Collins", "Dean",
    "Ellis", "Fisher", "Green", "Howard", "Irwin",
    "James", "Kelly", "Long", "Mason", "Norton",
    "Oliver", "Perry", "Reed", "Stevens", "Taylor",
    "Underhill", "Vance", "Webb", "Cross", "Yuan",
    "Zimmerman", "Avery", "Bell", "Cox", "Dunn",
    "Eaton", "Ford", "Grant", "Hunt", "Irons",
    "Jones", "Kim", "Lyons", "Murray", "Neal",
    "Orton", "Page", "Ramos", "Stone", "Todd",
    "Upton", "Vega", "Wolfe", "Knox", "Yates",
    "Zane", "Ash", "Blake", "Cruz", "Day",
]
STREETS = [
    "123 Magnolia Ln", "456 Peach Tree Dr", "789 Rosewood Ct",
    "321 Sycamore Ave", "654 Willow Creek Rd", "987 Blossom Way",
    "111 Dogwood Dr", "222 Ivy Hill Ln", "333 Cedar Ridge Rd",
    "444 Maple Grove Ct", "555 Sunflower St", "666 Honeysuckle Ln",
    "777 Bluebonnet Way", "888 Clover Field Dr", "999 Jasmine Ct",
    "101 Primrose Path", "202 Larkspur Ln", "303 Morning Glory Dr",
    "404 Camellia Ct", "505 Azalea Ave", "606 Dahlia Dr",
    "707 Wisteria Way", "808 Peony Pl", "909 Iris Ct",
    "1010 Violet Ave", "1111 Tulip Ln", "1212 Lily Rd",
    "1313 Orchid Way", "1414 Rose Ct", "1515 Daisy Dr",
]
CITIES_STATES = [
    ("Birmingham", "AL"), ("Huntsville", "AL"), ("Mobile", "AL"),
    ("Montgomery", "AL"), ("Tuscaloosa", "AL"), ("Decatur", "AL"),
    ("Florence", "AL"), ("Dothan", "AL"), ("Auburn", "AL"),
    ("Hoover", "AL"), ("Madison", "AL"), ("Vestavia Hills", "AL"),
    ("Prattville", "AL"), ("Phenix City", "AL"), ("Gadsden", "AL"),
]
ZIPS = [
    "35801", "35803", "35816", "36109", "36117",
    "35401", "35630", "36830", "35242", "36303",
    "35758", "35226", "36067", "36867", "35901",
]
TAGS_POOL = ["VIP", "Hostess", "Facial Client", "Warm Lead", "Regular"]

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

# Inventory: quantities sized to hit $5000+ retail
INVENTORY_ITEMS = [
    ("10217417", 8),   # $116 × 8  = $928
    ("10217415", 6),   # $116 × 6  = $696
    ("10223245", 4),   # $208 × 4  = $832
    ("10171886", 6),   # $60  × 6  = $360
    ("10198866", 4),   # $58  × 4  = $232
    ("10245671", 8),   # $44  × 8  = $352
    ("10176966", 6),   # $32  × 6  = $192
    ("10163626", 6),   # $40  × 6  = $240
    ("10217519", 8),   # $28  × 8  = $224
    ("10163625", 5),   # $34  × 5  = $170
    ("10176450", 10),  # $20  × 10 = $200
    ("10176452", 8),   # $20  × 8  = $160
    ("10190365", 8),   # $18  × 8  = $144
    ("10180358", 6),   # $16  × 6  = $96
    ("10107305", 3),   # $60  × 3  = $180
    ("10157924", 8),   # $20  × 8  = $160
    ("10208384", 5),   # $55  × 5  = $275
    ("10235051", 3),   # $55  × 3  = $165
    ("10213898", 5),   # $42  × 5  = $210
    ("10233587", 3),   # $56  × 3  = $168
    # Total: ~$5,984
]


def _serial(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def setup():
    if BACKUP_PATH.exists():
        print(f"Backup already exists at {BACKUP_PATH} — skipping to protect original data.")
        print("Delete it first if you want a fresh backup.")
        return

    conn = connect()
    cur  = conn.cursor()

    # ── Backup all relevant tables ───────────────────────────────────────────
    backup = {}
    for table in [
        "customers", "orders", "inventory",
        "customer_followups", "customer_birthday_followups",
        "pcp_enrollments", "pcp_lookbook_followups",
        "inventory_order_items", "inventory_intouch_imports",
    ]:
        cur.execute(f"SELECT * FROM {table} WHERE consultant_id = %s", (CONSULTANT_ID,))
        backup[table] = [dict(r) for r in cur.fetchall()]

    # order_items has no consultant_id — join through orders
    cur.execute("""
        SELECT oi.* FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.consultant_id = %s
    """, (CONSULTANT_ID,))
    backup["order_items"] = [dict(r) for r in cur.fetchall()]

    BACKUP_PATH.write_text(json.dumps(backup, default=_serial, indent=2))
    print(f"✅ Backed up production data → {BACKUP_PATH}")
    for k, v in backup.items():
        print(f"   {k}: {len(v)} rows")

    # ── Wipe consultant 1's data (FK-safe order) ─────────────────────────────
    cur.execute("DELETE FROM pcp_lookbook_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_birthday_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM pcp_enrollments WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id=%s)", (CONSULTANT_ID,))
    cur.execute("DELETE FROM orders WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customers WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory_order_items WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory_intouch_imports WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory WHERE consultant_id=%s", (CONSULTANT_ID,))
    print("✅ Wiped existing data")

    random.seed(42)
    today = date.today()

    # ── Build customer list ──────────────────────────────────────────────────
    names = list(zip(FIRST_NAMES, LAST_NAMES))
    random.shuffle(names)
    names = names[:100]

    # Birthday this week: May 18–24
    THIS_WEEK_BDS  = [f"05-{d:02d}" for d in range(18, 25)]  # 7 dates
    # Birthday this month (not this week): May 1–17 and May 25–31
    THIS_MONTH_BDS = [f"05-{d:02d}" for d in list(range(1, 18)) + list(range(25, 32))]
    # Other birthdays spread across the year
    OTHER_BDS = [
        "01-08", "01-22", "02-14", "02-28", "03-07", "03-19",
        "04-03", "04-15", "06-11", "06-28", "07-04", "07-19",
        "08-05", "08-22", "09-10", "09-27", "10-14", "10-30",
        "11-08", "11-25", "12-03", "12-19", "01-31", "02-07",
        "03-25", "04-29", "06-05", "07-14", "08-31", "09-15",
        "10-06", "11-18", "12-28", "01-15", "02-20", "03-11",
        "04-08", "06-22", "07-30", "08-10", "09-04", "10-21",
        "11-02", "12-15", "01-28", "02-03", "03-30", "04-25",
        "06-16", "07-08", "08-27", "09-20", "10-09", "11-14",
        "12-07", "01-19", "02-25", "03-04", "04-18", "06-30",
        "07-23", "08-15", "09-03", "10-28", "11-21", "12-01",
        "01-05", "02-11", "03-22", "04-01", "06-07", "07-27",
    ]

    # Assign birthdays: first 12 get this-week, next 18 get this-month, rest other
    birthdays = []
    for i in range(100):
        if i < 12:
            birthdays.append(THIS_WEEK_BDS[i % len(THIS_WEEK_BDS)])
        elif i < 30:
            birthdays.append(THIS_MONTH_BDS[(i - 12) % len(THIS_MONTH_BDS)])
        else:
            birthdays.append(OTHER_BDS[(i - 30) % len(OTHER_BDS)])

    random.shuffle(birthdays)  # mix them up so birthday customers aren't all first

    # ── Insert 100 customers ─────────────────────────────────────────────────
    customer_ids = []
    for i, (first, last) in enumerate(names):
        city, state = random.choice(CITIES_STATES)
        street      = STREETS[i % len(STREETS)]
        phone_num   = f"256{random.randint(3000000, 9999999)}"
        email       = f"{first.lower()}.{last.lower()}demo@gmail.com"
        birthday    = birthdays[i]
        zip_code    = random.choice(ZIPS)
        tags        = random.choice(TAGS_POOL) if random.random() < 0.35 else None

        cur.execute("""
            INSERT INTO customers
              (consultant_id, first_name, last_name, email, phone, street, city, state,
               postal_code, birthday, source_status, tags)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)
            RETURNING id
        """, (CONSULTANT_ID, first, last, email, phone_num, street, city, state,
              zip_code, birthday, tags))
        customer_ids.append(cur.fetchone()["id"])

    print(f"✅ Inserted {len(customer_ids)} customers")

    # ── Order date buckets ───────────────────────────────────────────────────
    def date_in(start_days_ago, end_days_ago):
        d = random.randint(end_days_ago, start_days_ago)
        return today - timedelta(days=d)

    # Customers 0–9: NO orders (new pipeline customers)
    # Customers 10–19: gone quiet (orders 6+ months ago only)
    # Customers 20–99: active — get orders in various buckets

    products = list(ORDER_PRODUCTS)

    def insert_order(cid, order_date):
        items = random.sample(products, random.randint(1, 4))
        total = sum(p[2] for p in items)
        cur.execute("""
            INSERT INTO orders (consultant_id, customer_id, order_date, total, source)
            VALUES (%s,%s,%s,%s,'consultant') RETURNING id
        """, (CONSULTANT_ID, cid, order_date.isoformat(), total))
        oid = cur.fetchone()["id"]
        for sku, name, price in items:
            cur.execute("""
                INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity)
                VALUES (%s,%s,%s,%s,1)
            """, (oid, sku, name, price))
        return oid

    order_count = 0

    for i, cid in enumerate(customer_ids):
        if i < 10:
            # No orders — new customers
            continue
        elif i < 20:
            # Gone quiet — last order 6+ months ago
            insert_order(cid, date_in(240, 180))
            order_count += 1
        elif i < 30:
            # Today
            insert_order(cid, today)
            if random.random() < 0.4:
                insert_order(cid, date_in(60, 30))
            order_count += 1
        elif i < 45:
            # This week (May 13–17)
            insert_order(cid, date_in(5, 1))
            if random.random() < 0.5:
                insert_order(cid, date_in(90, 45))
            order_count += 1
        elif i < 60:
            # This month (May 1–12)
            insert_order(cid, date_in(17, 6))
            if random.random() < 0.4:
                insert_order(cid, date_in(120, 60))
            order_count += 1
        elif i < 80:
            # Last month (April)
            insert_order(cid, date_in(48, 19))
            if random.random() < 0.3:
                insert_order(cid, date_in(180, 90))
            order_count += 1
        else:
            # 6 months ago (Nov–Dec 2025)
            insert_order(cid, date_in(200, 160))
            order_count += 1

    print(f"✅ Inserted ~{order_count} orders")

    # ── PCP enrollments (30 customers from the active group) ────────────────
    pcp_candidates = customer_ids[20:60]  # active customers with recent orders
    pcp_selected   = random.sample(pcp_candidates, 30)
    scraped_at     = datetime.now().isoformat()

    for cid in pcp_selected:
        # look up the name we inserted
        cur.execute("SELECT first_name, last_name FROM customers WHERE id=%s", (cid,))
        row = cur.fetchone()
        pcp_name = f"{row['first_name']} {row['last_name']}"
        cur.execute("""
            INSERT INTO pcp_enrollments (consultant_id, pcp_name, quarter, enrolled, scraped_at, customer_id)
            VALUES (%s,%s,'2026-Q2',true,%s,%s)
        """, (CONSULTANT_ID, pcp_name, scraped_at, cid))

    print(f"✅ Enrolled 30 customers in PCP")

    # ── Inventory ────────────────────────────────────────────────────────────
    for sku, qty in INVENTORY_ITEMS:
        cur.execute("""
            INSERT INTO inventory (consultant_id, sku, qty_on_hand)
            VALUES (%s,%s,%s)
        """, (CONSULTANT_ID, sku, qty))

    print(f"✅ Inserted {len(INVENTORY_ITEMS)} inventory items (~$5,984 retail)")

    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ Demo setup complete. Run 'python demo_setup_prod.py restore' after the presentation.")


def restore():
    if not BACKUP_PATH.exists():
        print(f"❌ No backup found at {BACKUP_PATH}")
        return

    backup = json.loads(BACKUP_PATH.read_text())
    conn   = connect()
    cur    = conn.cursor()

    # Wipe demo data (FK-safe order)
    cur.execute("DELETE FROM pcp_lookbook_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_birthday_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_followups WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM pcp_enrollments WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id=%s)", (CONSULTANT_ID,))
    cur.execute("DELETE FROM orders WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customers WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory_order_items WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory_intouch_imports WHERE consultant_id=%s", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory WHERE consultant_id=%s", (CONSULTANT_ID,))

    def _restore_table(table, rows):
        if not rows:
            return
        for row in rows:
            cols = ", ".join(row.keys())
            vals = ", ".join(["%s"] * len(row))
            cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({vals})", list(row.values()))
        print(f"   restored {table}: {len(rows)} rows")

    _restore_table("customers",                   backup.get("customers", []))
    _restore_table("orders",                      backup.get("orders", []))
    _restore_table("order_items",                 backup.get("order_items", []))
    _restore_table("inventory",                   backup.get("inventory", []))
    _restore_table("customer_followups",          backup.get("customer_followups", []))
    _restore_table("customer_birthday_followups", backup.get("customer_birthday_followups", []))
    _restore_table("pcp_enrollments",             backup.get("pcp_enrollments", []))
    _restore_table("pcp_lookbook_followups",      backup.get("pcp_lookbook_followups", []))
    _restore_table("inventory_order_items",       backup.get("inventory_order_items", []))
    _restore_table("inventory_intouch_imports",   backup.get("inventory_intouch_imports", []))

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✅ Production data restored. You can delete {BACKUP_PATH} once everything looks good.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "restore":
        restore()
    else:
        print("Usage: python demo_setup_prod.py setup|restore")
