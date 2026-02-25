##

# billing_routes.py
from __future__ import annotations

import os
import time

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from db import connect, is_postgres

router = APIRouter()

PH = "%s" if is_postgres() else "?"


def _now_sql() -> str:
    return "NOW()" if is_postgres() else "datetime('now')"


def _ts_to_utc_string(ts: int | None) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(ts)))


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _update_consultant_by_email(
    email: str,
    *,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    billing_status: str | None = None,
    trial_end: str | None = None,
    current_period_end: str | None = None,
    cancel_at_period_end: int | None = None,
) -> int:
    """
    Still kept for utility, but your NEW flow should mostly update by customer_id.
    """
    email = _norm_email(email)
    if not email:
        return 0

    sets = []
    params: list = []

    if stripe_customer_id is not None:
        sets.append(f"stripe_customer_id={PH}")
        params.append(stripe_customer_id)

    if stripe_subscription_id is not None:
        sets.append(f"stripe_subscription_id={PH}")
        params.append(stripe_subscription_id)

    if billing_status is not None:
        sets.append(f"billing_status={PH}")
        params.append(billing_status)

    if trial_end is not None:
        sets.append(f"trial_end={PH}")
        params.append(trial_end)

    if current_period_end is not None:
        sets.append(f"current_period_end={PH}")
        params.append(current_period_end)

    if cancel_at_period_end is not None:
        sets.append(f"cancel_at_period_end={PH}")
        params.append(int(cancel_at_period_end))

    # stamp last event if we touched anything
    sets.append(f"last_billing_event_at={_now_sql()}")

    if not sets:
        return 0

    params.append(email)

    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE consultants
            SET {", ".join(sets)}
            WHERE lower(email)={PH}
            """,
            params,
        )
        conn.commit()
        return int(getattr(cur, "rowcount", 0) or 0)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _update_consultant_by_customer_id(
    customer_id: str,
    *,
    stripe_subscription_id: str | None = None,
    billing_status: str | None = None,
    trial_end: str | None = None,
    current_period_end: str | None = None,
    cancel_at_period_end: int | None = None,
) -> int:
    customer_id = (customer_id or "").strip()
    if not customer_id:
        return 0

    sets = []
    params: list = []

    if stripe_subscription_id is not None:
        sets.append(f"stripe_subscription_id={PH}")
        params.append(stripe_subscription_id)

    if billing_status is not None:
        sets.append(f"billing_status={PH}")
        params.append(billing_status)

    if trial_end is not None:
        sets.append(f"trial_end={PH}")
        params.append(trial_end)

    if current_period_end is not None:
        sets.append(f"current_period_end={PH}")
        params.append(current_period_end)

    if cancel_at_period_end is not None:
        sets.append(f"cancel_at_period_end={PH}")
        params.append(int(cancel_at_period_end))

    sets.append(f"last_billing_event_at={_now_sql()}")

    if not sets:
        return 0

    params.append(customer_id)

    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE consultants
            SET {", ".join(sets)}
            WHERE stripe_customer_id={PH}
            """,
            params,
        )
        conn.commit()
        return int(getattr(cur, "rowcount", 0) or 0)
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _ts_now() -> int:
    return int(time.time())

def _safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def _get_consultant_by_customer_id(customer_id: str):
    customer_id = (customer_id or "").strip()
    if not customer_id:
        return None

    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT id, referred_by_consultant_id, stripe_subscription_id
            FROM consultants
            WHERE stripe_customer_id={PH}
            """,
            (customer_id,),
        )
        return cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def _get_referrer_customer_id(referrer_cid: int) -> str:
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT stripe_customer_id FROM consultants WHERE id={PH}",
            (int(referrer_cid),),
        )
        row = cur.fetchone()
        if not row:
            return ""
        return (row[0] or "").strip()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _referral_already_rewarded(referee_cid: int) -> bool:
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT rewarded_at, status
            FROM referrals
            WHERE referee_consultant_id={PH}
            LIMIT 1
            """,
            (int(referee_cid),),
        )
        row = cur.fetchone()
        if not row:
            return False
        rewarded_at = (row[0] or "").strip() if row[0] is not None else ""
        status = (row[1] or "").strip().lower() if row[1] is not None else ""
        return bool(rewarded_at) or status == "rewarded"
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def _mark_referral_rewarded(referrer_cid: int, referee_cid: int) -> bool:
    """
    Atomically marks referral as rewarded IF it wasn't already.
    Returns True only if we transitioned from not-rewarded -> rewarded.
    """
    conn = connect()
    cur = conn.cursor()
    try:
        # Mark referrals table ONLY if not already rewarded
        cur.execute(
            f"""
            UPDATE referrals
            SET status='rewarded',
                rewarded_at={_now_sql()}
            WHERE referee_consultant_id={PH}
              AND (rewarded_at IS NULL OR rewarded_at = '')
              AND (status IS NULL OR lower(status) != 'rewarded')
            """,
            (int(referee_cid),),
        )
        changed = int(getattr(cur, "rowcount", 0) or 0)

        if changed:
            # Stamp ONLY the referee (not both)
            cur.execute(
                f"""
                UPDATE consultants
                SET referral_rewarded_at={_now_sql()}
                WHERE id={PH}
                """,
                (int(referee_cid),),
            )

        conn.commit()
        return changed == 1

    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

import json

def _get_price_amount_and_currency() -> tuple[int, str]:
    """
    Returns (unit_amount, currency) for the STRIPE_PRICE_ID in env.
    """
    price_id = (os.getenv("STRIPE_PRICE_ID") or "").strip()
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID not set")

    p = stripe.Price.retrieve(price_id, expand=["currency_options"])
    unit_amount = int(p.get("unit_amount") or 0)
    currency = (p.get("currency") or "usd").lower()
    return unit_amount, currency


def _clean_stripe_customer_id(raw: str) -> str:
    """
    Self-heal: sometimes stripe_customer_id accidentally gets stored as a full JSON object string.
    We extract the first cus_XXXX token if present.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # already clean
    if s.startswith("cus_") and " " not in s and "\n" not in s and "{" not in s:
        return s

    import re
    m = re.search(r"(cus_[A-Za-z0-9]+)", s)
    return (m.group(1) if m else "").strip()

# -------------------------
# Browser billing flow endpoints
# -------------------------
@router.get("/billing/start")
def billing_start(request: Request):
    stripe.api_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    PRICE_ID = (os.getenv("STRIPE_PRICE_ID") or "").strip()
    APP_BASE_URL = (os.getenv("APP_BASE_URL") or "http://localhost:8000").strip()

    if not stripe.api_key:
        return HTMLResponse("STRIPE_SECRET_KEY not set", status_code=500)
    if not PRICE_ID:
        return HTMLResponse("STRIPE_PRICE_ID not set", status_code=500)

    cid = request.session.get("consultant_id")
    if not cid:
        return RedirectResponse("/onboard", status_code=302)

    cid_int = int(cid)

    # ---- Read onboarding email + existing stripe_customer_id + billing_status from DB
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT email, stripe_customer_id, billing_status, referred_by_consultant_id
            FROM consultants
            WHERE id={PH}
            """,
            (cid_int,),
        )
        row = cur.fetchone()
        if not row:
            return RedirectResponse("/onboard", status_code=302)

        # sqlite row tuple order matches SELECT above
        email = (row[0] or "").strip().lower()
        stripe_customer_id = (row[1] or "").strip()
        billing_status = (row[2] or "").strip().lower()
        
        referred_by_consultant_id = row[3]
        try:
            ref_id_int = int(referred_by_consultant_id) if referred_by_consultant_id is not None else 0
        except Exception:
            ref_id_int = 0

        trial_days = 30 if ref_id_int > 0 else 7

        if not email:
            return HTMLResponse("Missing email for account.", status_code=400)

        # ✅ FIX #2: If already paid/trialing, do NOT send them back to Stripe
        if billing_status in ("active", "trialing"):
            return RedirectResponse("/app", status_code=302)

        # ---- Create Stripe customer if we don't have one yet (locks email)
        if not stripe_customer_id:
            cust = stripe.Customer.create(
                email=email,
                metadata={"consultant_id": str(cid_int), "source": "mypinkassistant"},
            )
            stripe_customer_id = cust["id"]

            cur.execute(
                f"""
                UPDATE consultants
                SET stripe_customer_id={PH},
                    last_billing_event_at={_now_sql()}
                WHERE id={PH}
                """,
                (stripe_customer_id, cid_int),
            )
            conn.commit()

    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    # ---- Create checkout session tied to that customer (email locked)
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=stripe_customer_id,
        line_items=[{"price": PRICE_ID, "quantity": 1}],
        subscription_data={"trial_period_days": trial_days},
        success_url=f"{APP_BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{APP_BASE_URL}/billing/cancel",
        client_reference_id=str(cid_int),
        metadata={
            "consultant_id": str(cid_int),
            "source": "mypinkassistant",
            "trial_days": str(trial_days),
            "referred_by": str(ref_id_int) if ref_id_int > 0 else "",
        },
        allow_promotion_codes=True,
    )

    return HTMLResponse(
    f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <meta http-equiv="refresh" content="0; url={session.url}">
        <title>Redirecting…</title>
      </head>
      <body style="font-family:system-ui,-apple-system,Segoe UI,Roboto;padding:24px">
        <p>Redirecting to secure payment…</p>
        <p>If you are not redirected automatically, <a href="{session.url}">tap here to continue</a>.</p>
      </body>
    </html>
    """,
    status_code=200,
    )


@router.get("/billing/cancel")
def billing_cancel():
    return RedirectResponse("/splash.html", status_code=302)


@router.get("/billing/success")
def billing_success(request: Request, session_id: str = ""):
    """
    ✅ FIX #1: NEW FLOW bridge
    onboard created the consultant + set consultant_id in session,
    billing/start created checkout session tied to that consultant/customer.
    billing/success just verifies the checkout and sends to /app.
    """
    if not session_id:
        return RedirectResponse("/splash.html", status_code=302)

    stripe.api_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not stripe.api_key:
        return HTMLResponse("Stripe not configured.", status_code=500)

    try:
        s = stripe.checkout.Session.retrieve(
            session_id,
            expand=["customer", "subscription", "customer_details"],
        )
    except Exception as e:
        return HTMLResponse(f"Stripe error: {e}", status_code=400)

    if (s.get("mode") or "").strip() != "subscription":
        return HTMLResponse("Invalid checkout session mode.", status_code=400)

    payment_status = (s.get("payment_status") or "").strip()
    if payment_status not in ("paid", "no_payment_required"):
        return RedirectResponse("/billing/cancel", status_code=302)

    # ✅ Always trust the checkout session's client_reference_id
    cid_str = (s.get("client_reference_id") or "").strip()
    try:
        cid_int = int(cid_str)
    except Exception:
        cid_int = 0

    if not cid_int:
        return RedirectResponse("/login", status_code=302)

    # ✅ Clear any stale login, then set the correct one
    request.session.pop("consultant_id", None)
    request.session["consultant_id"] = cid_int

    return RedirectResponse("/app", status_code=302)



@router.get("/billing/portal")
def billing_portal(request: Request):
    stripe.api_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    APP_BASE_URL = (os.getenv("APP_BASE_URL") or "http://localhost:8000").strip()

    if not stripe.api_key:
        return HTMLResponse("Stripe not configured.", status_code=500)

    cid = request.session.get("consultant_id")
    if not cid:
        return RedirectResponse("/login", status_code=302)

    cid_int = int(cid)

    # ---- Get stripe_customer_id + stripe_subscription_id
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT stripe_customer_id, stripe_subscription_id
            FROM consultants
            WHERE id={PH}
            """,
            (cid_int,),
        )
        row = cur.fetchone()
        if not row:
            return RedirectResponse("/settings", status_code=302)

        raw_customer_id = (row[0] or "").strip()
        stripe_subscription_id = (row[1] or "").strip()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    # ---- Self-heal corrupted stored value
    stripe_customer_id = _clean_stripe_customer_id(raw_customer_id)

    # If we cleaned it and it changed, update DB
    if stripe_customer_id and stripe_customer_id != raw_customer_id:
        conn = connect()
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE consultants
                SET stripe_customer_id={PH},
                    last_billing_event_at={_now_sql()}
                WHERE id={PH}
                """,
                (stripe_customer_id, cid_int),
            )
            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            conn.close()

    # ✅ Edge-case fix: if they never subscribed (abandoned checkout),
    # portal is not useful—send to checkout.
    if not stripe_customer_id or not stripe_subscription_id:
        return RedirectResponse("/billing/start", status_code=302)

    # ---- Create portal session
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{APP_BASE_URL}/billing/return",
        )
    except Exception as e:
        return HTMLResponse(f"Stripe portal error: {e}", status_code=400)

    return RedirectResponse(session.url, status_code=303)


@router.get("/billing/return")
def billing_return(request: Request):
    cid = request.session.get("consultant_id")
    if not cid:
        return RedirectResponse("/login", status_code=302)

    return RedirectResponse("/settings", status_code=302)
# -------------------------
# Optional API checkout creation endpoint
# (useful later if you want JS to request a session)
# -------------------------
class CheckoutRequest(BaseModel):
    email: str | None = None


@router.post("/api/billing/create-checkout-session")
def create_checkout_session(body: CheckoutRequest):
    stripe.api_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    price_id = (os.getenv("STRIPE_PRICE_ID") or "").strip()
    app_base_url = (os.getenv("APP_BASE_URL") or "http://localhost:8000").strip()

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY not set")
    if not price_id:
        raise HTTPException(status_code=500, detail="STRIPE_PRICE_ID not set")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={"trial_period_days": 7},
            success_url=f"{app_base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{app_base_url}/billing/cancel",
            allow_promotion_codes=True,
            metadata={"source": "mypinkassistant"},
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# -------------------------
# Stripe Webhook (still valuable after account exists)
# -------------------------
@router.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    stripe.api_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    webhook_secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()

    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    if not webhook_secret:
        print("[Webhook] STRIPE_WEBHOOK_SECRET missing")
        return JSONResponse({"ok": False, "error": "STRIPE_WEBHOOK_SECRET not set"}, status_code=400)

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig,
            secret=webhook_secret,
        )
    except Exception as e:
        print("[Webhook] Verify failed:", repr(e))
        return JSONResponse({"ok": False, "error": f"verify failed: {e}"}, status_code=400)

    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    try:
        ##
        if etype == "checkout.session.completed":
            customer_id = (obj.get("customer") or "").strip()
            subscription_id = (obj.get("subscription") or "").strip()

            # 🔥 IMPORTANT: get consultant id from the checkout session
            cid_str = (obj.get("client_reference_id") or "").strip()

            try:
                cid_int = int(cid_str) if cid_str else 0
            except Exception:
                cid_int = 0

            updated = 0

            if cid_int:
                # ✅ Update the EXACT consultant who started checkout
                conn = connect()
                cur = conn.cursor()
                try:
                    cur.execute(
                        f"""
                        UPDATE consultants
                        SET stripe_customer_id={PH},
                            stripe_subscription_id={PH},
                            billing_status='trialing',
                            last_billing_event_at={_now_sql()}
                        WHERE id={PH}
                        """,
                        (customer_id or None, subscription_id or None, cid_int),
                    )
                    conn.commit()
                    updated = int(getattr(cur, "rowcount", 0) or 0)
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    conn.close()
            else:
                # fallback (should almost never happen)
                updated = _update_consultant_by_customer_id(
                    customer_id,
                    stripe_subscription_id=subscription_id or None,
                    billing_status="trialing",
                )

            print(f"[Webhook] OK: {etype} (cid={cid_str or 'none'}, updated_rows={updated})")

        elif etype == "customer.subscription.deleted":
            customer_id = (obj.get("customer") or "").strip()
            subscription_id = (obj.get("id") or "").strip()

            updated = _update_consultant_by_customer_id(
                customer_id,
                stripe_subscription_id=subscription_id or None,
                billing_status="canceled",
                cancel_at_period_end=0,
            )
            print(f"[Webhook] OK: {etype} (cust={customer_id}, updated_rows={updated})")

        elif etype == "invoice.paid":
            customer_id = (obj.get("customer") or "").strip()

            # 1) mark the payer as active
            updated = _update_consultant_by_customer_id(customer_id, billing_status="active")

            # Guardrail A: only reward on an invoice that actually collected money
            amount_paid = int(obj.get("amount_paid") or 0)  # cents
            billing_reason = (obj.get("billing_reason") or "").strip()

            if amount_paid <= 0:
                print(f"[Referral] Skip: invoice.paid but amount_paid={amount_paid} (billing_reason={billing_reason})")
                print(f"[Webhook] OK: {etype} (cust={customer_id}, updated_rows={updated})")
                return {"ok": True}

            # 2) Referral reward logic
            row = _get_consultant_by_customer_id(customer_id)
            if row:
                referee_cid = int(row[0] or 0)
                referrer_cid = row[1]
                referrer_cid_int = int(referrer_cid) if referrer_cid is not None else 0

                if referee_cid and referrer_cid_int:
                    # Fast exit if already rewarded
                    if _referral_already_rewarded(referee_cid):
                        print(f"[Referral] Already rewarded for referee={referee_cid}, skipping")
                    else:
                        referrer_customer_id = _get_referrer_customer_id(referrer_cid_int)
                        if not referrer_customer_id:
                            print(f"[Referral] No stripe_customer_id for referrer={referrer_cid_int} (cannot credit)")
                        else:
                            try:
                                amount, currency = _get_price_amount_and_currency()
                                if amount <= 0:
                                    print("[Referral] Price amount is 0; did not credit")
                                else:
                                    # ✅ Credit first (so we don't mark rewarded if Stripe fails)
                                    stripe.Customer.create_balance_transaction(
                                        referrer_customer_id,
                                        amount=-int(amount),  # negative = credit
                                        currency=currency,
                                        description=f"MyPinkAssistant referral reward (referee={referee_cid})",
                                    )

                                    # ✅ Then mark rewarded (atomic/one-time)
                                    did_mark = _mark_referral_rewarded(referrer_cid_int, referee_cid)
                                    if did_mark:
                                        print(f"[Referral] Credited referrer={referrer_cid_int} for referee={referee_cid} amount={amount} {currency}")
                                    else:
                                        # This can happen if two webhooks race; credit already applied though.
                                        print(f"[Referral] NOTE: credited but DB already marked rewarded for referee={referee_cid} (race)")
                            except Exception as e:
                                print(f"[Referral] FAILED to credit referrer={referrer_cid_int}: {repr(e)}")

            print(f"[Webhook] OK: {etype} (cust={customer_id}, updated_rows={updated})")

        elif etype == "invoice.payment_failed":
            customer_id = (obj.get("customer") or "").strip()
            updated = _update_consultant_by_customer_id(customer_id, billing_status="past_due")
            print(f"[Webhook] OK: {etype} (cust={customer_id}, updated_rows={updated})")

        else:
            print("[Webhook] OK (ignored):", etype)

        return {"ok": True}

    except Exception as e:
        print("[Webhook] handler error:", repr(e))
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)