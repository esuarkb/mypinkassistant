"""
Permanent demo account seeder — PRODUCTION Postgres, consultant_id 1
(briankrause@gmail.com).

Replaces demo_setup_prod.py (deleted 2026-07-26; in git history if ever needed),
which did a backup/restore dance around each demo. That script assumed
the account was temporarily borrowed for a presentation and had to be handed
back; as of 2026-07-26 consultant 1 is a PERMANENT demo account, excluded from
every recurring sync (see demo_accounts.py), so there is nothing to restore and
no backup to keep. Re-run this any time to reshape the demo data.

Everything it seeds is fabricated:
  * Names are female US Survivor contestants — recognisable, and unmistakably
    not real Mary Kay customers.
  * Phones are 256-555-01xx. The 555-01xx block is reserved for fiction, so a
    webinar attendee who taps a follow-up card's tap-to-text button on a shared
    screen cannot reach a real person.
  * Emails are @example.com (an IANA reserved domain — cannot receive mail).

Products, prices and categories are read LIVE from catalog/en.csv rather than
hardcoded. The old script's hardcoded SKU list had rotted badly — 11 of its 20
inventory SKUs no longer existed in the catalog and several survivors were
flagged "(Old SKU)", which would have demoed discontinued products.

Usage:
    python demo_seed.py            # show what it would do, then ask
    python demo_seed.py --yes      # run without the prompt
"""
import csv
import random
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras
from dotenv import dotenv_values

CONSULTANT_ID = 1
EXPECTED_EMAIL = "briankrause@gmail.com"   # guard: refuse to wipe anything else
PCP_QUARTER = "2026-Q3"
CATALOG = "catalog/en.csv"

# Follow-up windows are 1-4 / 10-18 / 50-70 days (followup_store.py:201), so
# these three offsets land dead centre in each of the 2+2+2 buckets.
ORDER_DAY_OFFSETS = [2, 14, 60]

cfg = dotenv_values(".env.production")
DATABASE_URL = cfg["DATABASE_URL"]


def connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


# ── 100 female US Survivor contestants ───────────────────────────────────────
SURVIVOR_WOMEN = [
    ("Tina", "Wesson"), ("Vecepia", "Towery"), ("Jenna", "Morasca"),
    ("Sandra", "Diaz-Twine"), ("Amber", "Brkich"), ("Danni", "Boatwright"),
    ("Parvati", "Shallow"), ("Natalie", "White"), ("Sophie", "Clarke"),
    ("Denise", "Stapley"), ("Kim", "Spradlin"), ("Natalie", "Anderson"),
    ("Michele", "Fitzgerald"), ("Sarah", "Lacina"), ("Erika", "Casupanan"),
    ("Maryanne", "Oketch"), ("Dee", "Valladares"), ("Kenzie", "Petty"),
    ("Rachel", "LaMont"), ("Colleen", "Haskell"), ("Kelly", "Wiglesworth"),
    ("Sue", "Hawk"), ("Elisabeth", "Filarski"), ("Jerri", "Manthey"),
    ("Alicia", "Calaway"), ("Ghandia", "Johnson"), ("Shii Ann", "Huang"),
    ("Deena", "Bennett"), ("Heidi", "Strobel"), ("Christy", "Smith"),
    ("Lill", "Morris"), ("Darrah", "Johnson"), ("Ami", "Cusack"),
    ("Eliza", "Orlins"), ("Twila", "Tanner"), ("Julie", "Berry"),
    ("Scout", "Lee"), ("Stephenie", "LaGrossa"), ("Jenn", "Lyon"),
    ("Courtney", "Yates"), ("Amanda", "Kimmel"), ("Cirie", "Fields"),
    ("Peih-Gee", "Law"), ("Denise", "Martin"), ("Crystal", "Cox"),
    ("Sugar", "Kiper"), ("Corinne", "Kaplan"), ("Taj", "Johnson-George"),
    ("Sierra", "Reed"), ("Natalie", "Bolton"), ("Monica", "Padilla"),
    ("Laura", "Morett"), ("Brenda", "Lowe"), ("Andrea", "Boehlke"),
    ("Ashley", "Underwood"), ("Whitney", "Duncan"), ("Kat", "Edorsson"),
    ("Chelsea", "Meissner"), ("Christina", "Cha"), ("Abi-Maria", "Gomes"),
    ("Lisa", "Whelchel"), ("Dawn", "Meehan"), ("Katie", "Collins"),
    ("Trish", "Hegarty"), ("Kass", "McQuillen"), ("Jaclyn", "Schultz"),
    ("Missy", "Payne"), ("Baylor", "Wilson"), ("Jenn", "Brown"),
    ("Carolyn", "Rivera"), ("Sierra", "Thomas"), ("Kelley", "Wentworth"),
    ("Kimmi", "Kappenberg"), ("Aubry", "Bracco"), ("Cydney", "Gillon"),
    ("Hannah", "Shapiro"), ("Sunday", "Burquest"), ("Ashley", "Nolan"),
    ("Chrissy", "Hofbeck"), ("Angela", "Perkins"), ("Kellyn", "Bechtold"),
    ("Alison", "Raybould"), ("Gabby", "Pascuzzi"), ("Julia", "Carter"),
    ("Aurora", "McCreary"), ("Karishma", "Patel"), ("Elaine", "Stott"),
    ("Janet", "Carbin"), ("Kellee", "Kim"), ("Noura", "Salman"),
    ("Shan", "Smith"), ("Liana", "Wallace"), ("Evvie", "Jagoda"),
    ("Tiffany", "Seely"), ("Lindsay", "Dolashewich"), ("Drea", "Wheeler"),
    ("Cassidy", "Clark"), ("Karla", "Godoy"), ("Carolyn", "Wiger"),
    ("Liz", "Wilcox"),
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

# Inventory: current SKUs only, quantities sized to land near $6k retail.
INVENTORY_ITEMS = [
    ("10254309", 8),   # TimeWise Miracle Set - Normal/Dry
    ("10254308", 6),   # TimeWise Miracle Set - Combination/Oily
    ("10257837", 3),   # Beyond Ultimate TimeWise Miracle Set - Normal/Dry
    ("10243732", 2),   # TimeWise Repair Volu-Firm Set
    ("10257238", 2),   # Ultimate TimeWise Miracle Set - Normal/Dry
    ("10230672", 4),   # Mary Kay Hydrating Regimen - Normal/Dry
    ("10198866", 4),   # TimeWise Microdermabrasion Plus Set
    ("10233587", 3),   # Clear Proof Acne System Set
    ("10257266", 4),   # TimeWise Repair Volu-Firm Day Cream SPF 30
    ("10107305", 3),   # Mary Kay Essential Brush Collection
    ("10235051", 3),   # Mary Kay Confidently You Eau de Parfum
    ("10094305", 3),   # Live Fearlessly Eau de Parfum
    ("10192900", 3),   # Belara Eau de Parfum
    ("10090638", 6),   # White Tea & Citrus Satin Hands Pampering Set
    ("10238148", 4),   # Fragrance-Free Satin Hands Pampering Set
    ("10091493", 6),   # White Tea & Citrus Satin Body Silkening Shea Lotion
    ("10091502", 5),   # White Tea & Citrus Satin Body Indulgent Shea Wash
    ("10235969", 4),   # Mary Kay Eye Shadow Palette - Outer Glow
    ("10210787", 6),   # TimeWise Luminous 3D Foundation - Light 3
    ("10143940", 3),   # Mary Kay Travel Roll-Up Bag
]

CATEGORIES = ["skincare", "makeup", "body", "fragrance"]


def load_catalog():
    """Return {sku: row} and {category: [rows]} for current, priced products."""
    by_sku, by_cat = {}, defaultdict(list)
    with open(CATALOG, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name = r.get("product_name") or ""
            price = r.get("price") or ""
            # "(Old SKU)" rows are discontinued predecessors — never demo those
            if "Old SKU" in name or not price:
                continue
            try:
                r["price_f"] = float(price)
            except ValueError:
                continue
            if r["price_f"] <= 0:
                continue
            by_sku[r["sku"]] = r
            if r.get("category") in CATEGORIES:
                by_cat[r["category"]].append(r)
    return by_sku, by_cat


def build_birthdays(today):
    """100 MM-DD birthdays: every ISO week of the year covered, plus clusters
    in the current week and current month so the demo queries are never empty."""
    year = today.year
    weeks = defaultdict(list)
    d = date(year, 1, 1)
    while d.year == year:
        if not (d.month == 2 and d.day == 29):      # skip leap day
            weeks[d.isocalendar()[1]].append(d)
        d += timedelta(days=1)

    rnd = random.Random(20260726)
    # 1. one birthday in every ISO week of the year, so no week of the year is
    #    ever empty however far ahead the demo account gets used
    picks = [rnd.choice(days) for _, days in sorted(weeks.items())]

    # 2. thicken the windows the demo actually asks for. NOTE these are ROLLING
    #    windows, not calendar weeks: crm_store.get_customers_by_birthday_period
    #    treats "week" as today..today+6 and "next_week" as today+7..today+13
    #    (crm_store.py:1644-1652). Clustering on the ISO week instead leaves
    #    "birthdays this week" nearly empty whenever the demo runs late in a week.
    def span(first_day, last_day):
        days = [today + timedelta(days=n) for n in range(first_day, last_day + 1)]
        return [d for d in days if not (d.month == 2 and d.day == 29)]

    def spread(days, n):
        """Round-robin rather than random, so the window fills evenly instead
        of stacking several customers on one date."""
        return [days[i % len(days)] for i in range(n)]

    picks += spread(span(0, 6), 9)      # "this week"  (today..+6)
    picks += spread(span(7, 13), 5)     # "next week"  (+7..+13)
    this_month = [d for days in weeks.values() for d in days if d.month == today.month]
    picks += [rnd.choice(this_month) for _ in range(10)]    # rest of "this month"

    # 3. fill the rest at random across the year
    all_days = [d for days in weeks.values() for d in days]
    while len(picks) < 100:
        picks.append(rnd.choice(all_days))

    picks = picks[:100]
    rnd.shuffle(picks)
    return [f"{d.month:02d}-{d.day:02d}" for d in picks]


def slug(s):
    return re.sub(r"[^a-z]", "", s.lower())


def main(assume_yes=False):
    by_sku, by_cat = load_catalog()

    missing = [s for s, _ in INVENTORY_ITEMS if s not in by_sku]
    if missing:
        print(f"ERROR: inventory SKUs not in {CATALOG}: {missing}")
        return 1
    for cat in CATEGORIES:
        if not by_cat[cat]:
            print(f"ERROR: no current products in category {cat!r}")
            return 1

    conn = connect()
    cur = conn.cursor()

    # ── Guard: only ever touch the demo account ──────────────────────────────
    cur.execute("SELECT email FROM consultants WHERE id = %s", (CONSULTANT_ID,))
    row = cur.fetchone()
    if not row or row["email"].lower() != EXPECTED_EMAIL:
        print(f"ERROR: consultant {CONSULTANT_ID} is {row and row['email']!r}, "
              f"expected {EXPECTED_EMAIL!r}. Refusing to run.")
        return 1

    cur.execute("SELECT COUNT(*) AS n FROM customers WHERE consultant_id = %s", (CONSULTANT_ID,))
    existing = cur.fetchone()["n"]
    print(f"Target: consultant {CONSULTANT_ID} ({EXPECTED_EMAIL}) — {existing} customers will be deleted.")
    print(f"Seeding: 100 customers, {100 * len(ORDER_DAY_OFFSETS)} orders, "
          f"30 PCP enrolments, {len(INVENTORY_ITEMS)} inventory SKUs.")
    if not assume_yes:
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1

    today = date.today()
    rnd = random.Random(20260726)

    # ── Wipe (FK-safe order) ─────────────────────────────────────────────────
    for stmt in [
        "DELETE FROM pcp_lookbook_followups WHERE consultant_id=%s",
        "DELETE FROM customer_birthday_followups WHERE consultant_id=%s",
        "DELETE FROM customer_followups WHERE consultant_id=%s",
        "DELETE FROM pcp_enrollments WHERE consultant_id=%s",
        "DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE consultant_id=%s)",
        "DELETE FROM orders WHERE consultant_id=%s",
        "DELETE FROM customers WHERE consultant_id=%s",
        "DELETE FROM inventory_order_items WHERE consultant_id=%s",
        "DELETE FROM inventory_intouch_imports WHERE consultant_id=%s",
        "DELETE FROM inventory WHERE consultant_id=%s",
    ]:
        cur.execute(stmt, (CONSULTANT_ID,))
    print("Wiped existing data.")

    # ── Customers ────────────────────────────────────────────────────────────
    birthdays = build_birthdays(today)
    customer_ids = []
    for i, (first, last) in enumerate(SURVIVOR_WOMEN):
        city, state = CITIES_STATES[i % len(CITIES_STATES)]
        cur.execute("""
            INSERT INTO customers
              (consultant_id, first_name, last_name, email, phone, street, city, state,
               postal_code, birthday, source_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')
            RETURNING id
        """, (CONSULTANT_ID, first, last,
              f"{slug(first)}.{slug(last)}@example.com",
              f"256555{100 + i:04d}",                     # 256-555-01xx, reserved
              STREETS[i % len(STREETS)], city, state,
              rnd.choice(ZIPS), birthdays[i]))
        customer_ids.append(cur.fetchone()["id"])
    print(f"Inserted {len(customer_ids)} customers.")

    # ── Orders: one per follow-up window, 3 distinct categories per customer ─
    order_count = item_count = 0
    for cid in customer_ids:
        cats = rnd.sample(CATEGORIES, 3)
        for offset, cat in zip(ORDER_DAY_OFFSETS, cats):
            order_date = datetime.combine(today - timedelta(days=offset),
                                          datetime.min.time()).replace(hour=14)
            items = [rnd.choice(by_cat[cat])]
            for _ in range(rnd.randint(0, 2)):          # a little padding
                items.append(rnd.choice(by_cat[rnd.choice(CATEGORIES)]))

            total = sum(p["price_f"] for p in items)
            cur.execute("""
                INSERT INTO orders (consultant_id, customer_id, order_date, total, source)
                VALUES (%s,%s,%s,%s,'consultant') RETURNING id
            """, (CONSULTANT_ID, cid, order_date, round(total, 2)))
            oid = cur.fetchone()["id"]
            for p in items:
                cur.execute("""
                    INSERT INTO order_items (order_id, sku, product_name, unit_price, quantity)
                    VALUES (%s,%s,%s,%s,1)
                """, (oid, p["sku"], p["product_name"], p["price_f"]))
                item_count += 1
            order_count += 1
    print(f"Inserted {order_count} orders / {item_count} items "
          f"at {ORDER_DAY_OFFSETS} days ago.")

    # ── PCP enrolments ───────────────────────────────────────────────────────
    scraped_at = datetime.now().isoformat()
    for cid in rnd.sample(customer_ids, 30):
        cur.execute("SELECT first_name, last_name FROM customers WHERE id=%s", (cid,))
        r = cur.fetchone()
        cur.execute("""
            INSERT INTO pcp_enrollments (consultant_id, pcp_name, quarter, enrolled, scraped_at, customer_id)
            VALUES (%s,%s,%s,true,%s,%s)
        """, (CONSULTANT_ID, f"{r['first_name']} {r['last_name']}", PCP_QUARTER, scraped_at, cid))
    print(f"Enrolled 30 customers in PCP ({PCP_QUARTER}).")

    # ── Inventory ────────────────────────────────────────────────────────────
    retail = 0.0
    for sku, qty in INVENTORY_ITEMS:
        cur.execute("INSERT INTO inventory (consultant_id, sku, qty_on_hand) VALUES (%s,%s,%s)",
                    (CONSULTANT_ID, sku, qty))
        retail += by_sku[sku]["price_f"] * qty
    print(f"Inserted {len(INVENTORY_ITEMS)} inventory SKUs (${retail:,.2f} retail).")

    conn.commit()
    cur.close()
    conn.close()
    print("\nDemo account seeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main(assume_yes="--yes" in sys.argv))
