"""
Correction script — populates inventory_order_items from already-imported orders
and rebuilds inventory.qty_on_hand from that data.

Run one consultant at a time:
    python fix_inventory_order_items.py <consultant_id>
    python fix_inventory_order_items.py 1
"""
import sys
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
    iu_pass = fernet.decrypt(iu_pass_enc.encode()).decode()
    print(f"Consultant: {email} (id={consultant_id})")
    print(f"  InTouch user: {iu_user}")
    print(f"  Signed up: {created_at.date()}")

    # Orders to scrape: imported AFTER signup day, not already in order_items
    cur.execute("""
        SELECT imp.order_no
        FROM inventory_intouch_imports imp
        WHERE imp.consultant_id = %s
          AND imp.imported_at::date > %s::date
          AND imp.consumer_order_id = ''
          AND imp.order_no NOT IN (
              SELECT DISTINCT order_no FROM inventory_order_items
              WHERE consultant_id = %s
          )
        ORDER BY imp.imported_at
    """, (consultant_id, created_at, consultant_id))
    orders_to_scrape = [r[0] for r in cur.fetchall()]
    print(f"\nOrders to scrape: {len(orders_to_scrape)}")
    for o in orders_to_scrape:
        print(f"  {o}")

    if not orders_to_scrape:
        print("Nothing to scrape.")
    else:
        # Scrape each order and store line items
        sys.path.insert(0, str(Path(__file__).parent / "playwright_automation"))
        from inventory_import import login_order_site, scrape_order_detail

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            login_order_site(page, iu_user, iu_pass)

            for order_no in orders_to_scrape:
                # Find the order link on the 365-day list
                from playwright_automation.inventory_import import ORDER_SITE_BASE, ORDER_TYPE_COSMETIC
                search_url = (
                    f"{ORDER_SITE_BASE}/orders?lang=en_US"
                    f"&placedFor=yourself&orderDate=days90"
                    f"&orderType={ORDER_TYPE_COSMETIC}"
                )
                page.goto(search_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)

                href = None
                for link in page.locator("a").all():
                    try:
                        text = (link.text_content() or "").strip()
                        h = link.get_attribute("href") or ""
                        if text == order_no and "orderdetails" in h:
                            href = h
                            break
                    except Exception:
                        continue

                if not href:
                    print(f"  [{order_no}] not found on order list — skipping")
                    continue

                detail = scrape_order_detail(page, href)
                order_type = detail["order_type"].lower()
                order_source = detail["order_source"].lower()
                items = detail["items"]

                # Skip orders placed before the consultant signed up
                from datetime import datetime
                order_date_str = detail.get("order_date", "")
                if order_date_str:
                    try:
                        order_date = datetime.strptime(order_date_str, "%m/%d/%Y").date()
                        if order_date < created_at.date():
                            print(f"  [{order_no}] skipping — order date {order_date} is before signup {created_at.date()}")
                            continue
                    except ValueError:
                        pass

                if order_type != "cosmetic":
                    print(f"  [{order_no}] skipping — type={detail['order_type']!r}")
                    continue
                if order_source == "cds":
                    print(f"  [{order_no}] skipping — CDS")
                    continue
                if not items:
                    print(f"  [{order_no}] no items found — skipping")
                    continue

                # Save line items
                cur.execute(
                    "DELETE FROM inventory_order_items WHERE consultant_id = %s AND order_no = %s",
                    (consultant_id, order_no)
                )
                cur.executemany(
                    "INSERT INTO inventory_order_items (consultant_id, order_no, sku, qty) VALUES (%s, %s, %s, %s)",
                    [(consultant_id, order_no, item["sku"], item["qty"]) for item in items]
                )
                conn.commit()
                total_qty = sum(i["qty"] for i in items)
                print(f"  [{order_no}] saved {len(items)} SKUs, {total_qty} total qty  (type={detail['order_type']!r})")

            browser.close()

    # Show what we now have in inventory_order_items (stock items)
    cur.execute("""
        SELECT COUNT(DISTINCT order_no), COUNT(*), SUM(qty)
        FROM inventory_order_items WHERE consultant_id = %s
    """, (consultant_id,))
    r = cur.fetchone()
    print(f"\nStock items stored: {r[0]} stock orders, {r[1]} SKU rows, {r[2]} total qty")
    print("\nStep 1 complete. Verify stock items before touching on-hand counts.")

    conn.close()
    print("\nDone.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fix_inventory_order_items.py <consultant_id>")
        sys.exit(1)
    main(int(sys.argv[1]))
