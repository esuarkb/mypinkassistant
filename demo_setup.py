"""
Demo data setup for Facebook presentation.

Usage:
    python demo_setup.py setup    # back up DB and load fake data
    python demo_setup.py restore  # restore original DB from backup
"""
import sys
import shutil
import sqlite3
import random
from datetime import date, timedelta
from pathlib import Path

DB_PATH     = Path("data/mk.db")
BACKUP_PATH = Path("data/mk_backup_presentation.db")
CONSULTANT_ID = 1

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

# (sku, product_name, price)
ORDER_PRODUCTS = [
    ("10217417", "TimeWise Miracle Set - Normal/Dry", 116.00),
    ("10217415", "TimeWise Miracle Set - Combination/Oily", 116.00),
    ("10171886", "TimeWise Replenishing Serum C+E", 60.00),
    ("10198866", "TimeWise Microdermabrasion Plus Set", 58.00),
    ("10176966", "TimeWise Moisture Renewing Gel Mask", 32.00),
    ("10213898", "Mary Kay Satin Hands Pampering Set", 42.00),
    ("10245671", "White Tea & Citrus Satin Hands Pampering Set", 44.00),
    ("10176450", "Mary Kay Ultimate Mascara - Black", 20.00),
    ("10190365", "Mary Kay Unlimited Lip Gloss - Pink Chiffon", 18.00),
    ("10180358", "Mary Kay Lip Liner - Blush", 16.00),
    ("10163626", "TimeWise Age Minimize 3D Eye Cream", 40.00),
    ("10217519", "Mary Kay CC Cream SPF 15 - Light to Medium", 28.00),
    ("10163625", "TimeWise Age Minimize 3D Day Cream SPF 30", 34.00),
    ("10163627", "TimeWise Age Minimize 3D Night Cream", 34.00),
    ("10157924", "Mary Kay Micellar Water", 20.00),
    ("10233587", "Clear Proof Acne System Set", 56.00),
    ("10208384", "TimeWise Repair Volu-Firm Day Cream SPF 30", 55.00),
    ("10223245", "Beyond Ultimate TimeWise Miracle Set - C/O", 208.00),
    ("10107305", "Mary Kay Essential Brush Collection", 60.00),
    ("10176452", "Mary Kay Lash Love Mascara - I ♥ Black", 20.00),
]

# Items for ~$4000 inventory (sku, product_name, price, qty)
INVENTORY_ITEMS = [
    ("10217417", "TimeWise Miracle Set - Normal/Dry", 116.00, 4),
    ("10217415", "TimeWise Miracle Set - Combination/Oily", 116.00, 3),
    ("10223245", "Beyond Ultimate TimeWise Miracle Set - C/O", 208.00, 2),
    ("10171886", "TimeWise Replenishing Serum C+E", 60.00, 4),
    ("10198866", "TimeWise Microdermabrasion Plus Set", 58.00, 3),
    ("10245671", "White Tea & Citrus Satin Hands Pampering Set", 44.00, 5),
    ("10176966", "Mary Kay Gel Mask", 32.00, 4),
    ("10163626", "TimeWise Age Minimize 3D Eye Cream", 40.00, 4),
    ("10217519", "Mary Kay CC Cream SPF 15 - Light to Medium", 28.00, 5),
    ("10163625", "TimeWise Day Cream SPF 30", 34.00, 3),
    ("10176450", "Mary Kay Ultimate Mascara - Black", 20.00, 6),
    ("10176452", "Mary Kay Lash Love Mascara", 20.00, 4),
    ("10190365", "Mary Kay Lip Gloss - Pink Chiffon", 18.00, 5),
    ("10180358", "Mary Kay Lip Liner - Blush", 16.00, 4),
    ("10107305", "Mary Kay Essential Brush Collection", 60.00, 2),
    ("10157924", "Mary Kay Micellar Water", 20.00, 6),
    ("10211954", "TimeWise Repair Volu-Firm Set", 225.00, 2),
    ("10208384", "TimeWise Repair Volu-Firm Day Cream SPF 30", 55.00, 3),
    ("10235051", "Mary Kay Confidently You Eau de Parfum", 55.00, 2),
    ("10213898", "Mary Kay Satin Hands Pampering Set", 42.00, 3),
]
# Total: ~4*116 + 3*116 + 2*208 + 4*60 + 3*58 + 5*44 + 4*32 + 4*40 + 5*28 + 3*34 + 6*20 + 4*20 + 5*18 + 4*16 + 2*60 + 6*20
# = 464+348+416+240+174+220+128+160+140+102+120+80+90+64+120+120 = ~2986 ... let me just use qty


def setup():
    if BACKUP_PATH.exists():
        print(f"Backup already exists at {BACKUP_PATH} — skipping backup to avoid overwriting original.")
        print("If you want a fresh backup, delete the existing one first.")
    else:
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print(f"✅ Backed up {DB_PATH} → {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Clear existing data for consultant 1
    cur.execute("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id=?)", (CONSULTANT_ID,))
    cur.execute("DELETE FROM orders WHERE consultant_id=?", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_followups WHERE consultant_id=?", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customer_birthday_followups WHERE consultant_id=?", (CONSULTANT_ID,))
    cur.execute("DELETE FROM pcp_enrollments WHERE consultant_id=?", (CONSULTANT_ID,))
    cur.execute("DELETE FROM customers WHERE consultant_id=?", (CONSULTANT_ID,))
    cur.execute("DELETE FROM inventory WHERE consultant_id=?", (CONSULTANT_ID,))

    random.seed(42)
    today = date.today()

    # Insert 20 fake customers
    customer_ids = []
    names = list(zip(FIRST_NAMES, LAST_NAMES))
    random.shuffle(names)
    for i, (first, last) in enumerate(names):
        city, state = random.choice(CITIES_STATES)
        zip_code    = random.choice(ZIPS)
        street      = STREETS[i]
        phone_num   = f"256{random.randint(3000000, 9999999)}"
        email       = f"{first.lower()}.{last.lower()}@gmail.com"
        birthday    = BIRTHDAYS[i]
        cur.execute("""
            INSERT INTO customers
              (consultant_id, first_name, last_name, email, phone, street, city, state, postal_code, birthday, source_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,'active')
        """, (CONSULTANT_ID, first, last, email, phone_num, street, city, state, zip_code, birthday))
        customer_ids.append(cur.lastrowid)

    # Insert 1-2 orders per customer with 2-3 items each
    products = list(ORDER_PRODUCTS)
    for cid in customer_ids:
        num_orders = random.randint(1, 2)
        for o in range(num_orders):
            days_back   = random.randint(14, 400)
            order_date  = (today - timedelta(days=days_back)).isoformat()
            items       = random.sample(products, random.randint(2, 3))
            total       = sum(p[2] for p in items)
            cur.execute("""
                INSERT INTO orders (consultant_id, customer_id, order_date, total, source)
                VALUES (?,?,?,?,'consultant')
            """, (CONSULTANT_ID, cid, order_date, total))
            oid = cur.lastrowid
            for sku, name, price in items:
                cur.execute("""
                    INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity)
                    VALUES (?,?,?,?,1)
                """, (oid, sku, name, price))

    # Insert inventory (~$4000 on hand)
    for sku, name, price, qty in INVENTORY_ITEMS:
        cur.execute("""
            INSERT INTO inventory (consultant_id, sku, qty_on_hand)
            VALUES (?,?,?)
        """, (CONSULTANT_ID, sku, qty))

    conn.commit()
    conn.close()

    total_inv = sum(p * q for _, _, p, q in INVENTORY_ITEMS)
    print(f"✅ Inserted 20 demo customers")
    print(f"✅ Inserted orders with 2-3 items each")
    print(f"✅ Inserted {len(INVENTORY_ITEMS)} inventory SKUs — estimated retail value ${total_inv:,.2f}")
    print(f"\nRun 'python demo_setup.py restore' after the presentation to get your real data back.")


def restore():
    if not BACKUP_PATH.exists():
        print(f"❌ No backup found at {BACKUP_PATH}")
        return
    shutil.copy2(BACKUP_PATH, DB_PATH)
    print(f"✅ Restored {BACKUP_PATH} → {DB_PATH}")
    print("Your original data is back.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "restore":
        restore()
    else:
        print("Usage: python demo_setup.py setup|restore")
