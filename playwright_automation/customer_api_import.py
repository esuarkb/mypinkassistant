# playwright_automation/customer_api_import.py
from playwright.sync_api import Page

_CUSTOMER_LIST_URL = "https://apps.marykayintouch.com/customer-list"
_APEX_FRAGMENT = "/webruntime/api/apex/execute"

_CUSTOMER_KEYS = frozenset({"firstName", "lastName", "ibcAccountId", "personEmail"})


def _parse_customers(body: dict) -> list[dict]:
    rv = body.get("returnValue")
    if isinstance(rv, list):
        return rv
    return []


def _looks_like_customers(records: list[dict]) -> bool:
    return bool(records) and bool(_CUSTOMER_KEYS & set(records[0].keys()))


def fetch_customer_list(page: Page) -> list[dict]:
    """
    Navigates to the InTouch customer-list page and captures the API response
    containing full customer data (Salesforce IDs, tags, addresses, etc.).
    Robust to MK renaming the apex method — filters by response body shape.
    """
    captured: dict[str, dict] = {}

    def _on_response(response):
        url = response.url
        if _APEX_FRAGMENT not in url:
            return
        short = url[url.find(_APEX_FRAGMENT):][:130]
        print(f"[CustomerApiImport] apex: {short}")
        try:
            body = response.json()
            customers = _parse_customers(body)
            if _looks_like_customers(customers):
                print(f"[CustomerApiImport] found {len(customers)} customer records")
                for c in customers:
                    cid = c.get("id") or str(id(c))
                    captured[cid] = c
        except Exception as e:
            print(f"[CustomerApiImport] parse error on {short}: {e}")

    page.on("response", _on_response)

    page.goto(_CUSTOMER_LIST_URL, wait_until="domcontentloaded")
    print(f"[CustomerApiImport] on {page.url} — waiting 15s for LWC wire call")
    page.wait_for_timeout(15000)

    if captured:
        print(f"[CustomerApiImport] captured {len(captured)} customers via page-load listener")
        page.remove_listener("response", _on_response)
        return list(captured.values())

    print("[CustomerApiImport] no customers on initial load — reloading to bust LWC cache")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(15000)

    page.remove_listener("response", _on_response)

    if captured:
        print(f"[CustomerApiImport] captured {len(captured)} customers via reload listener")
        return list(captured.values())

    print(f"[CustomerApiImport] no customer data found after page-load + reload. URL: {page.url}")
    return []
