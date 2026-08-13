# playwright_automation/order_detail_sync.py
import json
from datetime import date, timedelta
from playwright.sync_api import Page


_APEX_URL = (
    "https://apps.marykayintouch.com/webruntime/api/apex/execute"
    "?language=en-US&asGuest=false&htmlEncode=false"
)
# Compiled Salesforce class ref — may change on MK deploy
_APEX_CLASSNAME = "@udd/01pR30000011tgy"


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return date.min


def fetch_order_details(
    page: Page,
    order_ids_with_dates: list[tuple[str, str]],
    csrf_token: str,
    days: int | None = None,
) -> dict[str, list[dict]]:
    """
    Makes direct HTTP calls to getOrderSummaryRecordByIds for each order.
    - order_ids_with_dates: list of (intouch_order_id, order_date "YYYY-MM-DD")
    - days: if set, only fetch orders with date within last N days (7-day mode)
    - csrf_token: captured from the order list Apex request headers
    - Returns: {intouch_order_id: [productDetails list]}
    Archived orders should already be filtered out by the caller.
    """
    if days is not None:
        cutoff = date.today() - timedelta(days=days)
        filtered = [(oid, d) for oid, d in order_ids_with_dates if _parse_date(d) >= cutoff]
    else:
        filtered = list(order_ids_with_dates)

    if not filtered:
        print("[OrderDetailSync] no orders to fetch")
        return {}

    if not csrf_token:
        print("[OrderDetailSync] WARNING: no csrf_token — detail sync skipped")
        return {}

    headers = {
        "Content-Type": "application/json",
        "csrf-token": csrf_token,
    }

    results: dict[str, list[dict]] = {}
    success = 0
    errors = 0
    _logged_sample = False

    for i, (order_id, order_date) in enumerate(filtered):
        payload = {
            "namespace": "",
            "classname": _APEX_CLASSNAME,
            "method": "getOrderSummaryRecordByIds",
            "isContinuation": False,
            "params": {
                "orderSummaryId": order_id,
                "webStoreId": "",
                "isB2CFlow": True,
            },
            "cacheable": False,
        }
        try:
            resp = page.context.request.post(
                _APEX_URL,
                headers=headers,
                data=json.dumps(payload),
            )
            body = resp.json()

            # Log the first response shape so we can verify the structure
            if not _logged_sample:
                rv_sample = body.get("returnValue")
                if isinstance(rv_sample, dict):
                    print(f"[OrderDetailSync] returnValue keys (sample): {list(rv_sample.keys())[:10]}")
                else:
                    print(f"[OrderDetailSync] returnValue type (sample): {type(rv_sample)}")
                _logged_sample = True

            rv = body.get("returnValue") or {}
            # Try top-level productDetails first, then nested under orderDetails
            details = rv.get("productDetails") or (rv.get("orderDetails") or {}).get("productDetails") or []
            if isinstance(details, list) and details:
                results[order_id] = details
            success += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"[OrderDetailSync] error on order {order_id}: {e}")

        if (i + 1) % 50 == 0:
            print(f"[OrderDetailSync] {i + 1}/{len(filtered)} fetched — {len(results)} with details, {errors} errors")

    print(
        f"[OrderDetailSync] done: {success}/{len(filtered)} fetched, "
        f"{errors} errors, {len(results)} orders have product details"
    )
    return results


def fetch_order_records(
    page: Page,
    order_ids_with_dates: list[tuple[str, str]],
    csrf_token: str,
) -> dict[str, dict]:
    """
    Makes direct HTTP calls to getOrderRecordById for each order.
    This is the ONLY read surface that carries order-level money:
    TotalTaxAmount, TotalDiscount_rs__c (negative), GrandTotalAmount.
    The order LIST payload and getOrderSummaryRecordByIds have neither
    tax nor a usable discount (per-item productDiscountAmount is always '0').
    - order_ids_with_dates: list of (intouch_order_id, order_date "YYYY-MM-DD")
    - csrf_token: captured from the order list Apex request headers
    - Returns: {intouch_order_id: record dict}
    Caller pre-filters the list (see select_orders_for_detail_sync).
    """
    if not order_ids_with_dates:
        print("[OrderMoneySync] no orders to fetch")
        return {}

    if not csrf_token:
        print("[OrderMoneySync] WARNING: no csrf_token — money sync skipped")
        return {}

    headers = {
        "Content-Type": "application/json",
        "csrf-token": csrf_token,
    }

    results: dict[str, dict] = {}
    errors = 0

    for i, (order_id, _order_date) in enumerate(order_ids_with_dates):
        payload = {
            "namespace": "",
            "classname": _APEX_CLASSNAME,
            "method": "getOrderRecordById",
            "isContinuation": False,
            "params": {"orderSummaryId": order_id},
            "cacheable": False,
        }
        try:
            resp = page.context.request.post(
                _APEX_URL,
                headers=headers,
                data=json.dumps(payload),
            )
            rv = resp.json().get("returnValue")
            if isinstance(rv, dict) and rv.get("GrandTotalAmount") is not None:
                results[order_id] = rv
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"[OrderMoneySync] error on order {order_id}: {e}")

        if (i + 1) % 50 == 0:
            print(f"[OrderMoneySync] {i + 1}/{len(order_ids_with_dates)} fetched, {errors} errors")

    print(
        f"[OrderMoneySync] done: {len(results)}/{len(order_ids_with_dates)} records fetched, "
        f"{errors} errors"
    )
    return results
