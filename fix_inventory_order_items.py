"""
Correction script — populates inventory_order_items from the last 90 days
of cosmetic orders using the same logic as the nightly sync, then reports
what was found so we can compare against on-hand counts.

Run one consultant at a time:
    python fix_inventory_order_items.py <consultant_id>
    python fix_inventory_order_items.py 9
"""
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import dotenv_values
from cryptography.fernet import Fernet


def main(consultant_id: int) -> None:
    env = dotenv_values(Path(__file__).parent / ".env.production")
    db_url = env["DATABASE_URL"]
    enc_key = dotenv_values(Path(__file__).parent / ".env")["MK_ENC_KEY"]
    fernet = Fernet(enc_key.encode())

    import psycopg2
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Get consultant info
    cur.execute("""
        SELECT email, intouch_username, intouch_password_enc, created_at
        FROM consultants WHERE id = %s
    """, (consultant_id,))
    row = cur.fetchone()
    if not row:
        print(f"Consultant {consultant_id} not found.")
        return
    email, iu_user, iu_pass_enc, created_at = row
    signup_date = created_at.date()
    iu_pass = fernet.decrypt(iu_pass_enc.encode()).decode()
    print(f"Consultant: {email} (id={consultant_id})")
    print(f"  InTouch user: {iu_user}")
    print(f"  Signed up: {signup_date}")

    sys.path.insert(0, str(Path(__file__).parent))
    from playwright_automation.inventory_import import (
        login_order_site, fetch_cosmetic_order_links, scrape_order_detail
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        login_order_site(page, iu_user, iu_pass)

        order_links = fetch_cosmetic_order_links(page, "days90")
        print(f"\nOrders on 90-day cosmetic list: {len(order_links)}")

        # Clear existing stock items for this consultant before rebuilding
        cur.execute("DELETE FROM inventory_order_items WHERE consultant_id = %s", (consultant_id,))
        conn.commit()

        saved = 0
        skipped = []

        for link in order_links:
            order_no = link["order_no"]
            consumer_order_id = link.get("consumer_order_id", "")

            if consumer_order_id:
                skipped.append(f"  [{order_no}] skipping — customer order")
                continue

            detail = scrape_order_detail(page, link["href"])
            order_type = detail["order_type"].lower()
            order_source = detail["order_source"].lower()
            order_date_str = detail.get("order_date", "")

            if order_date_str:
                try:
                    order_date = datetime.strptime(order_date_str, "%m/%d/%Y").date()
                    if order_date < signup_date:
                        skipped.append(f"  [{order_no}] skipping — order date {order_date} before signup")
                        continue
                except ValueError:
                    pass

            if order_type != "cosmetic":
                skipped.append(f"  [{order_no}] skipping — type={detail['order_type']!r}")
                continue
            if order_source == "cds":
                skipped.append(f"  [{order_no}] skipping — CDS")
                continue
            if not detail["items"]:
                skipped.append(f"  [{order_no}] skipping — no items found")
                continue

            cur.executemany(
                "INSERT INTO inventory_order_items (consultant_id, order_no, sku, qty) VALUES (%s, %s, %s, %s)",
                [(consultant_id, order_no, item["sku"], item["qty"]) for item in detail["items"]]
            )
            conn.commit()
            total_qty = sum(i["qty"] for i in detail["items"])
            print(f"  [{order_no}] saved {len(detail['items'])} SKUs, {total_qty} qty  (date={order_date_str})")
            saved += 1

        browser.close()

    for s in skipped:
        print(s)

    cur.execute("""
        SELECT COUNT(DISTINCT order_no), COUNT(*), SUM(qty)
        FROM inventory_order_items WHERE consultant_id = %s
    """, (consultant_id,))
    r = cur.fetchone()
    print(f"\nStock items stored: {r[0]} stock orders, {r[1]} SKU rows, {r[2]} total qty")

    cur.execute("SELECT COUNT(*), SUM(qty_on_hand) FROM inventory WHERE consultant_id = %s", (consultant_id,))
    r = cur.fetchone()
    print(f"Current on-hand:    {r[0]} SKUs, {r[1]} total qty")

    print("\nStep 1 complete. Verify stock items before touching on-hand counts.")
    conn.close()
    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fix_inventory_order_items.py <consultant_id>")
        sys.exit(1)
    main(int(sys.argv[1]))
