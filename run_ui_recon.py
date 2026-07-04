"""
Read-only InTouch UI recon — "did Mary Kay change anything?"

Visits the three fragile surfaces (login/customer list, new-customer form,
order form), records the visible buttons / field names / key probes, and
diffs against the last known-good baseline. NO side effects: nothing is
saved or submitted — the new-customer form is abandoned by navigation and
the order form is closed with its Cancel button. Add to Bag is checked for
PRESENCE only, never clicked.

Built to be run quickly by an agent (headless by default) whenever a site
change is suspected — e.g. after a step-logging failure names a button.

Usage:
    python run_ui_recon.py             # headless, diff vs baseline
    python run_ui_recon.py --headed    # watch it
    python run_ui_recon.py --reset     # accept current state as new baseline

Exit code: 0 = no changes vs baseline, 1 = changes detected (or first run).
Credentials: INTOUCH_USER / INTOUCH_PASS from .env (same as other runners).
Baseline: data/ui_recon_baseline.json
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_automation.login import login_intouch

USERNAME = os.environ["INTOUCH_USER"]
PASSWORD = os.environ["INTOUCH_PASS"]

TEST_CUSTOMER = "Jane Doe"   # existing test customer in the account
PROBE_SKU = "10179024"       # Oil-Free Eye Makeup Remover — stable catalog item

BASELINE_PATH = Path(__file__).parent / "data" / "ui_recon_baseline.json"
CUSTOMER_LIST_URL = "https://apps.marykayintouch.com/customer-list"


def visible_buttons(page) -> list[str]:
    out = []
    for b in page.get_by_role("button").all():
        try:
            if b.is_visible():
                txt = " ".join((b.inner_text() or "").split())
                if txt:
                    out.append(txt)
        except Exception:
            continue
    return sorted(set(out))


def visible_textboxes(page) -> list[str]:
    out = []
    for t in page.get_by_role("textbox").all():
        try:
            if t.is_visible():
                name = (t.get_attribute("aria-label") or t.get_attribute("placeholder") or "").strip()
                if not name:
                    # accessible name often comes from a label — fall back to id prefix
                    name = (t.get_attribute("id") or "").split("-")[0]
                if name:
                    out.append(name)
        except Exception:
            continue
    return sorted(set(out))


def probe(page, description: str, locator) -> bool:
    try:
        found = locator.count() > 0 and locator.first.is_visible()
    except Exception:
        found = False
    print(f"    probe {'OK  ' if found else 'MISS'} {description}")
    return found


def main() -> int:
    headed = "--headed" in sys.argv
    reset = "--reset" in sys.argv
    snapshot: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()

        # ---- Surface 1: login + customer list ----
        print("\n=== SURFACE 1: login / customer list ===")
        login_intouch(page, USERNAME, PASSWORD)
        page.wait_for_timeout(2000)
        snapshot["customer_list"] = {
            "buttons": visible_buttons(page),
            "probes": {
                "search box ('Note Title' searchbox)": probe(
                    page, "search box ('Note Title' searchbox)",
                    page.get_by_role("searchbox", name="Note Title")),
            },
        }
        print(f"    buttons: {snapshot['customer_list']['buttons']}")

        # ---- Surface 2: new-customer form (opened, dumped, abandoned) ----
        print("\n=== SURFACE 2: new-customer form (no save) ===")
        page.get_by_role("button", name="New Customer").click()
        try:
            page.get_by_role("textbox", name="First Name").wait_for(state="visible", timeout=15000)
        except PlaywrightTimeoutError:
            print("    !! First Name field never appeared")
        page.wait_for_timeout(1500)
        snapshot["new_customer_form"] = {
            "buttons": visible_buttons(page),
            "textboxes": visible_textboxes(page),
            "probes": {
                "'Save New Customer' button": probe(
                    page, "'Save New Customer' button",
                    page.get_by_role("button", name="Save New Customer")),
                "'Email Address (Optional)' field": probe(
                    page, "'Email Address (Optional)' field",
                    page.get_by_role("textbox", name="Email Address (Optional)")),
                "'Birthday (Optional)' field": probe(
                    page, "'Birthday (Optional)' field",
                    page.get_by_role("textbox", name="Birthday (Optional)")),
            },
        }
        print(f"    textboxes: {snapshot['new_customer_form']['textboxes']}")
        # Abandon without saving
        page.goto(CUSTOMER_LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # ---- Surface 3: customer detail page + address dialog (explore, no save) ----
        print("\n=== SURFACE 3: customer detail + address dialog (no save) ===")
        page.get_by_role("searchbox", name="Note Title").fill(TEST_CUSTOMER)
        page.wait_for_timeout(800)
        page.get_by_text(TEST_CUSTOMER).first.click()
        page.wait_for_timeout(1500)
        detail = {
            "buttons": visible_buttons(page),
            "probes": {
                "'Add Order' button": probe(
                    page, "'Add Order' button", page.get_by_role("button", name="Add Order")),
                "subscriptions section (c-cmt-my-customer-details-subscriptions)": probe(
                    page, "subscriptions section",
                    page.locator("c-cmt-my-customer-details-subscriptions")),
                "'Add New Address' button": probe(
                    page, "'Add New Address' button",
                    page.get_by_role("button", name="Add New Address")),
            },
        }
        print(f"    detail buttons: {detail['buttons']}")
        # Open the address dialog if the button is there, dump it, close with Escape.
        # (Nothing is saved — only the dialog's 'Add New Address' submit would do that,
        # and we never click inside the dialog at all.)
        if detail["probes"]["'Add New Address' button"]:
            try:
                # Same retry pattern as production (new_customer.py) — InTouch
                # often ignores the first click on this button
                _first_name_field = page.locator('[id^="AddressFirstName-"]')
                for _ in range(4):
                    page.get_by_role("button", name="Add New Address").first.click()
                    page.wait_for_timeout(700)
                    try:
                        _first_name_field.wait_for(state="visible", timeout=1000)
                        break
                    except PlaywrightTimeoutError:
                        pass
                _first_name_field.wait_for(state="visible", timeout=3000)
                page.wait_for_timeout(700)
                dialog = page.get_by_role("dialog")
                detail["address_dialog"] = {
                    "buttons": sorted(set(
                        " ".join((b.inner_text() or "").split())
                        for b in dialog.get_by_role("button").all() if b.is_visible()
                    )),
                    "probes": {
                        "AddressFirstName field": probe(
                            page, "AddressFirstName field", page.locator('[id^="AddressFirstName-"]')),
                        "Street field": probe(page, "Street field", page.locator('[id^="Street-"]')),
                        "City field": probe(page, "City field", page.locator('[id^="City-"]')),
                        "PostalCode field": probe(
                            page, "PostalCode field", page.locator('[id^="PostalCode-"]')),
                        "state 'Select an option' dropdown": probe(
                            page, "state 'Select an option' dropdown",
                            dialog.get_by_role("button", name="Select an option")),
                        "'Add Apartment/Suite/Etc' button": probe(
                            page, "'Add Apartment/Suite/Etc' button",
                            dialog.get_by_role("button", name="Add Apartment/Suite/Etc")),
                    },
                }
                print(f"    dialog buttons: {detail['address_dialog']['buttons']}")
                page.keyboard.press("Escape")
                try:
                    page.locator('[id^="AddressFirstName-"]').wait_for(state="hidden", timeout=5000)
                except PlaywrightTimeoutError:
                    print("    !! address dialog did not close on Escape — navigating away instead")
                    page.goto(CUSTOMER_LIST_URL, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    page.get_by_role("searchbox", name="Note Title").fill(TEST_CUSTOMER)
                    page.wait_for_timeout(800)
                    page.get_by_text(TEST_CUSTOMER).first.click()
                page.wait_for_timeout(800)
            except PlaywrightTimeoutError:
                print("    !! address dialog failed to open")
                detail["address_dialog"] = {"buttons": [], "probes": {}}
        snapshot["customer_detail"] = detail

        # ---- Surface 4: order form (opened, probed, cancelled) ----
        print("\n=== SURFACE 4: order form (no save — closed via Cancel) ===")
        page.get_by_role("button", name="Add Order").click()
        page.wait_for_timeout(3000)
        order_probes = {
            "'My Inventory' fulfillment option": probe(
                page, "'My Inventory' fulfillment option", page.get_by_text("My Inventory")),
            "'Customer Delivery Service' fulfillment option": probe(
                page, "'Customer Delivery Service' fulfillment option",
                page.get_by_text("Customer Delivery Service")),
            "'Save and Review' button": probe(
                page, "'Save and Review' button", page.get_by_role("button", name="Save and Review")),
            "product search box": probe(
                page, "product search box", page.get_by_role("searchbox", name="Note Title")),
        }
        # SKU search → does 'Add to Bag' appear? (presence only — NEVER clicked)
        # InTouch's product search transiently returns nothing on a first try
        # (seen live 2026-07-03) — retry once before calling it broken, same as
        # a human would.
        found_sku = False
        for attempt in (1, 2):
            try:
                box = page.get_by_role("searchbox", name="Note Title")
                box.fill("")
                page.wait_for_timeout(300)
                box.fill(PROBE_SKU)
                page.locator(f"text={PROBE_SKU}").first.wait_for(timeout=12000)
                found_sku = True
                break
            except PlaywrightTimeoutError:
                print(f"    !! SKU {PROBE_SKU} produced no search result (attempt {attempt})")
        page.wait_for_timeout(500)
        if found_sku:
            order_probes["'Add to Bag' button after SKU search"] = probe(
                page, "'Add to Bag' button after SKU search",
                page.get_by_role("button", name="Add to Bag"))
        else:
            order_probes["'Add to Bag' button after SKU search"] = False
        snapshot["order_form"] = {
            "buttons": visible_buttons(page),
            "probes": order_probes,
        }
        # Close the draft cleanly
        try:
            page.get_by_role("button", name="Cancel").first.click()
            page.wait_for_timeout(1000)
        except Exception:
            page.goto(CUSTOMER_LIST_URL, wait_until="domcontentloaded")

        browser.close()

    # Hoist the nested address dialog into its own surface so the diff sees it
    _ad = snapshot.get("customer_detail", {}).pop("address_dialog", None)
    if _ad:
        snapshot["customer_detail.address_dialog"] = _ad

    # ---- Diff vs baseline ----
    if reset or not BASELINE_PATH.exists():
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(snapshot, indent=2))
        print(f"\nBaseline {'reset' if reset else 'created'}: {BASELINE_PATH}")
        return 1 if not reset else 0

    baseline = json.loads(BASELINE_PATH.read_text())
    changes: list[str] = []
    for surface, snap in snapshot.items():
        base = baseline.get(surface, {})
        for kind in ("buttons", "textboxes"):
            new = set(snap.get(kind, [])) - set(base.get(kind, []))
            gone = set(base.get(kind, [])) - set(snap.get(kind, []))
            for x in sorted(new):
                changes.append(f"[{surface}] NEW {kind[:-1]}: {x!r}")
            for x in sorted(gone):
                changes.append(f"[{surface}] MISSING {kind[:-1]} (possibly renamed): {x!r}")
        for name, ok in snap.get("probes", {}).items():
            was = base.get("probes", {}).get(name)
            if was is True and not ok:
                changes.append(f"[{surface}] PROBE BROKE: {name}")
            elif was is False and ok:
                changes.append(f"[{surface}] probe recovered: {name}")

    print("\n" + "=" * 50)
    if changes:
        print("*** CHANGES DETECTED vs BASELINE ***")
        for c in changes:
            print("  " + c)
        print(f"\nIf intentional/accepted: python run_ui_recon.py --reset")
        return 1
    print("No changes vs baseline — all surfaces look normal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
