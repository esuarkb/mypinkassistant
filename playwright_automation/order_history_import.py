# playwright_automation/order_history_import.py
from playwright.sync_api import Page

_ORDER_LIST_URL = "https://apps.marykayintouch.com/order-list"
_APEX_FRAGMENT = "/webruntime/api/apex/execute"

# Keys present in order records but not in other apex responses.
_ORDER_KEYS = frozenset({
    "GrandTotalAmount", "OrderItemSummaries",
    "CustomerAccount_lr__r", "OrderedDate_f__c", "OrderedDate",
})


def _parse_orders(body: dict) -> list[dict]:
    orders = body.get("returnValue") or []
    return orders if isinstance(orders, list) else []


def _looks_like_orders(records: list[dict]) -> bool:
    return bool(records) and bool(_ORDER_KEYS & set(records[0].keys()))


def fetch_order_history(page: Page) -> list[dict]:
    """
    Navigates to the InTouch order-list page and captures the order-list
    API response. Matches any cacheable apex response whose returnValue
    looks like order records — robust to MK renaming the method.
    """
    # Deduplicate by Salesforce order Id so a reload doesn't double-count.
    captured: dict[str, dict] = {}

    def _on_response(response):
        url = response.url
        if _APEX_FRAGMENT not in url:
            return
        short = url[url.find(_APEX_FRAGMENT):][:130]
        print(f"[OrderHistoryImport] apex: {short}")
        try:
            body = response.json()
            orders = _parse_orders(body)
            if orders:
                sample_keys = list(orders[0].keys())[:8]
                print(f"[OrderHistoryImport] returnValue[0] keys: {sample_keys}")
            if _looks_like_orders(orders):
                print(f"[OrderHistoryImport] found {len(orders)} orders: {short}")
                for o in orders:
                    oid = o.get("Id") or str(id(o))
                    captured[oid] = o
        except Exception as e:
            print(f"[OrderHistoryImport] parse error on {short}: {e}")

    page.on("response", _on_response)

    page.goto(_ORDER_LIST_URL, wait_until="domcontentloaded")
    print(f"[OrderHistoryImport] on {page.url} — polling for LWC wire call (max 15s)")
    for _ in range(30):
        if captured:
            break
        page.wait_for_timeout(500)

    if captured:
        print(f"[OrderHistoryImport] captured {len(captured)} orders via page-load listener")
        page.remove_listener("response", _on_response)
        return list(captured.values())

    print("[OrderHistoryImport] no orders on initial load — reloading to bust LWC cache")
    page.reload(wait_until="domcontentloaded")
    for _ in range(30):
        if captured:
            break
        page.wait_for_timeout(500)

    page.remove_listener("response", _on_response)

    if captured:
        print(f"[OrderHistoryImport] captured {len(captured)} orders via reload listener")
        return list(captured.values())

    print(f"[OrderHistoryImport] no orders found after page-load + reload — assuming zero orders. URL: {page.url}")
    return []
