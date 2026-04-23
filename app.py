##update app.py for admin page

# app.py
import os
from dotenv import load_dotenv
load_dotenv(override=True)  # must run before any module that reads DATABASE_URL at import time

import json
import time
import secrets
import hashlib
import logging
#from turtle import color
import requests
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Iterable, Optional, Sequence, Dict

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db import connect, is_postgres, tx
from db import get_system_setting, set_system_setting
from mk_chat_core import MKChatEngine, save_session_state, insert_job, maybe_queue_initial_customer_import
from billing_routes import router as billing_router

from auth_core import (
    authenticate,
    get_consultant,
    update_settings,
    set_consultant_password,
    create_consultant,
    get_consultant_full,  # must return dict-like with needed fields
    update_profile_and_intouch,
)

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
PAGES_DIR = BASE_DIR / "pages"

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(billing_router)

# -------------------------
# ENV
# -------------------------
SESSION_SECRET = os.environ.get("MK_SESSION_SECRET", "").strip()
if not SESSION_SECRET:
    raise RuntimeError(
        "MK_SESSION_SECRET is not set. Export MK_SESSION_SECRET before starting the server."
    )

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip()

# Treat Render as production by default
IS_PROD = bool(os.environ.get("RENDER")) or os.environ.get("ENV", "").strip().lower() in (
    "prod",
    "production",
)

# DB placeholder for sqlite vs postgres
PH = "%s" if is_postgres() else "?"

# used_at expression (sqlite vs postgres)
USED_AT_NOW_SQL = "NOW()" if is_postgres() else "datetime('now')"

# 30 days "remember me" + production cookie hardening
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=IS_PROD,  # Secure cookies in prod; keep working on http://localhost
)

# Public static assets ONLY
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


# -------------------------
# Security headers (simple + production-friendly)
# -------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)

    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    # CSP: allow inline styles because your pages use <style> blocks and some inline style=""
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )

    # HSTS only makes sense over HTTPS
    if IS_PROD:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return resp

import stripe

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "").strip()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000").strip()

stripe.api_key = STRIPE_SECRET_KEY

# -------------------------
# DB helpers
# -------------------------
def _conn():
    return connect()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_get(row, key, default=None):
    """Works with dict rows (psycopg dict_row), sqlite3.Row, tuples."""
    if row is None:
        return default
    try:
        return row.get(key, default)  # type: ignore
    except Exception:
        pass
    try:
        return row[key]  # type: ignore
    except Exception:
        return default


def _find_consultant_by_email(email: str):
    email = (email or "").strip().lower()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(f"SELECT id FROM consultants WHERE email={PH}", (email,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    cid = _row_get(row, "id", None)
    if cid is None:
        try:
            cid = row[0]
        except Exception:
            return None
    return int(cid)


import re
import secrets

def _generate_referral_code() -> str:
    # short + readable (8 chars). You can tweak length later.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # avoid confusing chars
    return "".join(secrets.choice(alphabet) for _ in range(8))

def get_or_create_referral_code(cid: int) -> str:
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT referral_code FROM consultants WHERE id={PH}", (int(cid),))
        row = cur.fetchone()
        existing = ""
        if row:
            try:
                existing = (row.get("referral_code") or "").strip()  # type: ignore
            except Exception:
                existing = (row[0] or "").strip()

        if existing:
            return existing

        # generate unique code
        for _ in range(10):
            code = _generate_referral_code()
            cur.execute(f"SELECT id FROM consultants WHERE referral_code={PH}", (code,))
            taken = cur.fetchone()
            if not taken:
                cur.execute(
                    f"UPDATE consultants SET referral_code={PH} WHERE id={PH}",
                    (code, int(cid)),
                )
                conn.commit()
                return code

        # extremely unlikely fallback
        code = _generate_referral_code() + _generate_referral_code()
        cur.execute(
            f"UPDATE consultants SET referral_code={PH} WHERE id={PH}",
            (code, int(cid)),
        )
        conn.commit()
        return code
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def apply_referral(referee_cid: int, ref_code: str) -> tuple[bool, str]:
    """
    Links referee -> referrer (one-time).

    Guard rails:
      - code must exist
      - cannot self-refer
      - referee can only be referred once
    """
    code = (ref_code or "").strip().upper()
    if not code:
        return (False, "Missing referral code")

    conn = _conn()
    cur = conn.cursor()
    try:
        # find referrer by code
        cur.execute(
            f"SELECT id FROM consultants WHERE referral_code={PH}",
            (code,),
        )
        r = cur.fetchone()
        if not r:
            return (False, "Invalid referral code")

        referrer_id = _row_get(r, "id", None) if _row_get(r, "id", None) is not None else r[0]
        referrer_id = int(referrer_id)

        if referrer_id == int(referee_cid):
            return (False, "You can’t use your own referral code")

        # if referee already has a referrer, do nothing (idempotent)
        cur.execute(
            f"SELECT referred_by_consultant_id FROM consultants WHERE id={PH}",
            (int(referee_cid),),
        )
        rr = cur.fetchone()
        existing = None
        if rr:
            existing = _row_get(rr, "referred_by_consultant_id", None)
            if existing is None:
                existing = rr[0]

        if existing:
            return (True, "Referral already applied")

        # set referee -> referrer and stamp applied_at
        cur.execute(
            f"""
            UPDATE consultants
            SET referred_by_consultant_id={PH},
                referral_applied_at={USED_AT_NOW_SQL}
            WHERE id={PH}
            """,
            (referrer_id, int(referee_cid)),
        )

        # audit row (UNIQUE(referee_consultant_id) prevents double)
        # do "ignore" in a DB-specific way
        if is_postgres():
            cur.execute(
                f"""
                INSERT INTO referrals (referrer_consultant_id, referee_consultant_id, applied_at, status)
                VALUES ({PH},{PH},NOW(),'applied')
                ON CONFLICT (referee_consultant_id) DO NOTHING
                """,
                (referrer_id, int(referee_cid)),
            )
        else:
            cur.execute(
                f"""
                INSERT OR IGNORE INTO referrals (referrer_consultant_id, referee_consultant_id, applied_at, status)
                VALUES ({PH},{PH},datetime('now'),'applied')
                """,
                (referrer_id, int(referee_cid)),
            )

        conn.commit()
        return (True, "Referral applied")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def get_billing_status_by_id(cid: int) -> str:
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT billing_status FROM consultants WHERE id={PH}", (int(cid),))
        row = cur.fetchone()
        if not row:
            return ""
        try:
            return (row.get("billing_status") or "").strip().lower()  # type: ignore
        except Exception:
            return (row[0] or "").strip().lower()
    finally:
        conn.close()


def billing_redirect_for_cid(cid: int) -> str:
    """
    If this consultant has a Stripe customer already, send them to the billing portal.
    Otherwise send them to Stripe checkout start.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT stripe_customer_id FROM consultants WHERE id={PH}",
            (int(cid),),
        )
        row = cur.fetchone()
        if not row:
            return "/billing/start"

        try:
            stripe_customer_id = (row.get("stripe_customer_id") or "").strip()  # type: ignore
        except Exception:
            stripe_customer_id = (row[0] or "").strip()

        return "/billing/portal" if stripe_customer_id else "/billing/start"
    finally:
        conn.close()

def require_active_subscription_by_id(cid: int) -> None:
    status = get_billing_status_by_id(cid)
    if status in ("active", "trialing"):
        return
    raise PermissionError(f"Billing inactive: {status or 'unknown'}")



def _update_name_fields(cid: int, first_name: str, last_name: str) -> None:
    """Save first/last name in DB (kept here so you don't have to edit auth_core)."""
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE consultants SET first_name={PH}, last_name={PH} WHERE id={PH}",
        (fn, ln, int(cid)),
    )
    conn.commit()
    conn.close()


# -------------------------
# Email (Resend)
# -------------------------
def _send_resend_email(to_email: str, subject: str, html: str) -> None:
    if not RESEND_API_KEY or not MAIL_FROM:
        raise RuntimeError("Email not configured. Set RESEND_API_KEY and MAIL_FROM in .env")

    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={"from": MAIL_FROM, "to": [to_email], "subject": subject, "html": html},
        timeout=15,
    )
    r.raise_for_status()


# -------------------------
# Auth helpers
# -------------------------
def require_login(request: Request) -> int:
    cid = request.session.get("consultant_id")
    if not cid:
        raise PermissionError("Not logged in")
    return int(cid)

def require_active_subscription(c: dict) -> None:
    """
    Allows access only if billing is good.
    For now we treat 'active' and 'trialing' as OK.
    Everything else -> blocked.
    """
    status = (c.get("billing_status") or "").strip().lower()
    if status in ("active", "trialing"):
        return
    raise PermissionError(f"Billing inactive: {status or 'unknown'}")

def require_admin(request: Request) -> int:
    """
    Admin gate (simple): allowlist by email in MK_ADMIN_EMAILS.
    Example: MK_ADMIN_EMAILS="you@email.com,partner@email.com"
    Fail-closed if not configured.
    """
    cid = require_login(request)
    c = get_consultant_full(cid) or {}
    email = (c.get("email") or "").strip().lower()

    allowed = os.environ.get("MK_ADMIN_EMAILS", "")
    allowed_set = {e.strip().lower() for e in allowed.split(",") if e.strip()}

    if not allowed_set:
        raise PermissionError("Admin access not configured (set MK_ADMIN_EMAILS)")

    if email not in allowed_set:
        raise PermissionError("Not authorized")

    return cid


def is_profile_complete(c: dict) -> bool:
    if not c:
        return False
    return (
        bool((c.get("first_name") or "").strip())
        and bool((c.get("last_name") or "").strip())
        and bool((c.get("intouch_username") or "").strip())
        and bool((c.get("intouch_password_enc") or "").strip())
    )



def _esc(value: str) -> str:
    import html
    return html.escape(str(value or ""))


def render_page(filename: str, replaces: dict | None = None) -> HTMLResponse:
    path = PAGES_DIR / filename
    if not path.exists():
        return HTMLResponse(f"Missing page: {filename}", status_code=500)

    html = path.read_text(encoding="utf-8")

    # Inject emergency banner (global UI guardrail)
    ui = get_ui_emergency()
    if ui["enabled"] and ui["message"]:
        banner = f"""
        <style>
        /* banner */
        #ui-emergency-banner {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 99999;
            background: #fff3cd;
            color: #856404;
            padding: 14px 16px;
            text-align: center;
            font-weight: 600;
            border-bottom: 1px solid #ffeeba;
        }}

        /* default: push page content down */
        body {{
            padding-top: 70px !important;
        }}

        /* login page compatibility (centering layouts) */
        html.ui-emergency-on body {{
            align-items: flex-start !important;
        }}
        </style>

        <div id="ui-emergency-banner">{ui["message"]}</div>

        <script>
        document.documentElement.classList.add("ui-emergency-on");
        </script>
        """

        if "<body" in html.lower():
            body_index = html.lower().find("<body")
            insert_index = html.find(">", body_index) + 1
            html = html[:insert_index] + banner + html[insert_index:]

    if replaces:
        for k, v in replaces.items():
            html = html.replace(k, v)

    return HTMLResponse(html)

def get_ui_emergency() -> dict:
    """
    Returns {"enabled": bool, "message": str}
    Reads from system_settings:
      - ui_emergency_enabled: "0"/"1"
      - ui_emergency_message: string
    """
    enabled_raw = (get_system_setting("ui_emergency_enabled", "0") or "0").strip()
    msg = (get_system_setting("ui_emergency_message", "") or "").strip()

    enabled = enabled_raw in ("1", "true", "yes", "on")
    return {"enabled": enabled, "message": msg}

def set_ui_emergency(enabled: bool, message: str) -> None:
    set_system_setting("ui_emergency_enabled", "1" if enabled else "0")
    set_system_setting("ui_emergency_message", (message or "").strip())

# Create the chat engine once (loads catalog once)
engine = MKChatEngine()


# -------------------------
# Public pages
# -------------------------
from urllib.parse import urlencode

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    # Prefer ref from URL, else session
    ref = (request.query_params.get("ref") or "").strip().upper()
    if not ref:
        ref = (request.session.get("referral_code") or "").strip().upper()

    # keep it in session once we see it
    if ref:
        request.session["referral_code"] = ref

    ref_qs = ""
    if ref:
        ref_qs = "?" + urlencode({"ref": ref})

    return render_page("landing.html", replaces={
        "{{REF_QS}}": ref_qs,
    })

from urllib.parse import urlencode

@app.get("/r/{code}")
def referral_landing(request: Request, code: str):
    code = (code or "").strip().upper()
    if code:
        request.session["referral_code"] = code
        return RedirectResponse(f"/?{urlencode({'ref': code})}", status_code=302)

    return RedirectResponse("/", status_code=302)

from urllib.parse import urlencode

@app.get("/splash.html", response_class=HTMLResponse)
def splash(request: Request):
    # Prefer ref from URL, else session
    ref = (request.query_params.get("ref") or "").strip().upper()
    if not ref:
        ref = (request.session.get("referral_code") or "").strip().upper()

    # Keep it in session once we see it
    if ref:
        request.session["referral_code"] = ref

    ref_qs = ""
    if ref:
        ref_qs = "?" + urlencode({"ref": ref})

    return render_page("splash.html", replaces={"{{REF_QS}}": ref_qs})

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()

from fastapi import Query

from urllib.parse import unquote_plus

@app.get("/onboard", response_class=HTMLResponse)
def onboard_get(
    request: Request,
    first_name: str = Query("", alias="first_name"),
    last_name: str = Query("", alias="last_name"),
    email: str = Query("", alias="email"),
    intouch_username: str = Query("", alias="intouch_username"),
    language: str = Query("en", alias="language"),
    error: str = Query("", alias="error"),
    ref: str = Query("", alias="ref"),
):
    if not ref:
        ref = (request.session.get("referral_code") or "").strip()
    cid = request.session.get("consultant_id")
    c = get_consultant_full(int(cid)) if cid else None

    if ref:
        ref_block = "<div class='welcome'>You've been invited! We're glad you're here 🎉</div>"
    else:
        ref_block = ""
        
    # If logged in + complete, go to app
    if c and is_profile_complete(c):
        return RedirectResponse("/app", status_code=302)

    # Prefer query param values (when bouncing back), otherwise DB, otherwise blank
    fn_val = (first_name or ((c.get("first_name") or "") if c else "")).strip()
    ln_val = (last_name or ((c.get("last_name") or "") if c else "")).strip()
    em_val = (email or ((c.get("email") or "") if c else "")).strip()
    iu_val = (intouch_username or ((c.get("intouch_username") or "") if c else "")).strip()

    lang = (language or (c.get("language") if c else "en") or "en").strip().lower()
    if lang not in ("en", "es"):
        lang = "en"

    error_block = f"<div class='err'>{error}</div>" if error else ""

    replaces = {
        "{{FIRST_NAME}}": fn_val,
        "{{LAST_NAME}}": ln_val,
        "{{EMAIL}}": em_val,
        "{{INTOUCH_USERNAME}}": iu_val,
        "{{EN_SELECTED}}": "selected" if lang == "en" else "",
        "{{ES_SELECTED}}": "selected" if lang == "es" else "",
        "{{ERROR_BLOCK}}": error_block,
        "{{REF}}": (ref or "").strip(),
        "{{REF_WELCOME}}": ref_block
    }
    return render_page("onboard.html", replaces=replaces)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    cid = request.session.get("consultant_id")
    if not cid:
        return render_page("login.html")

    c = get_consultant_full(int(cid)) or {}

    if not is_profile_complete(c):
        return RedirectResponse("/onboard", status_code=302)

    try:
        require_active_subscription_by_id(int(cid))
    except Exception:
        return RedirectResponse(billing_redirect_for_cid(int(cid)), status_code=302)

    return RedirectResponse("/app", status_code=302)


from fastapi.responses import HTMLResponse, RedirectResponse

@app.post("/login")
@limiter.limit("5/minute")
def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    email_norm = (email or "").strip().lower()

    cid = authenticate(email_norm, password)
    if not cid:
        return HTMLResponse(
            "Login failed. <a href='/login'>Try again</a>.",
            status_code=401,
        )

    # ✅ Login success always sets session (billing does NOT block authentication)
    request.session["consultant_id"] = int(cid)

    c = get_consultant_full(int(cid)) or {}

    # 1) If profile incomplete, finish onboarding first
    if not is_profile_complete(c):
        return RedirectResponse("/onboard", status_code=302)

    # 2) If billing inactive, send to Stripe checkout
    # Option A: if you already have require_active_subscription_by_id()
    try:
        require_active_subscription_by_id(int(cid))
    except Exception:
        return RedirectResponse(billing_redirect_for_cid(int(cid)), status_code=302)

    # Option B (if you do NOT have require_active_subscription_by_id):
    # try:
    #     require_active_subscription(c)
    # except PermissionError:
    #     return RedirectResponse("/billing/start", status_code=302)

    # 3) Otherwise go to app
    return RedirectResponse("/app", status_code=302)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


# -------------------------
# Forgot password
@app.get("/check-email")
def check_email(email: str = Query("", alias="email")):
    exists = bool(_find_consultant_by_email(email.strip().lower()))
    return JSONResponse({"exists": exists})


# -------------------------
@app.get("/forgot", response_class=HTMLResponse)
def forgot_get():
    return HTMLResponse(
        """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Forgot password • MyPinkAssistant</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto;background:#fff;color:#111;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}
    .card{width:min(460px,100%);border:1px solid #e8e8ee;border-radius:18px;padding:18px;box-shadow:0 10px 28px rgba(0,0,0,.07)}
    h1{margin:0 0 6px;text-align:center;font-size:18px}
    p{margin:0 0 12px;text-align:center;color:#666;font-size:13px;line-height:1.35}
    label{display:block;font-size:12px;color:#666;margin-top:12px}
    input{width:100%;margin-top:6px;padding:12px;border-radius:14px;border:1px solid #e8e8ee;font-size:14px}
    button{width:100%;margin-top:14px;padding:12px;border:0;border-radius:14px;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#e91e63,#c2185b);color:#fff}
    a{color:#e91e63;text-decoration:none;font-weight:600}
    .back{display:block;margin-top:14px;text-align:center;font-size:13px}
  </style>
</head>
<body>
  <div class="card">
    <h1>Reset your password</h1>
    <p>Enter the email you used for MyPinkAssistant. We’ll send a reset link.</p>
    <form method="post" action="/forgot">
      <label>Email</label>
      <input name="email" type="email" autocomplete="username" required />
      <button type="submit">Send reset link</button>
    </form>
    <a class="back" href="/login">← Back to login</a>
  </div>
</body>
</html>
"""
    )


@app.post("/forgot", response_class=HTMLResponse)
@limiter.limit("5/minute")
def forgot_post(request: Request, email: str = Form(...)):
    try:
        cid = _find_consultant_by_email(email)
        if cid and APP_BASE_URL:
            token = secrets.token_urlsafe(32)
            token_hash = _hash_token(token)

            now = int(time.time())
            expires = now + (60 * 30)  # 30 minutes
            expires_str = str(expires)

            conn = _conn()
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO password_resets (consultant_id, token_hash, expires_at) VALUES ({PH}, {PH}, {PH})",
                (int(cid), token_hash, expires_str),
            )
            conn.commit()
            conn.close()

            link = f"{APP_BASE_URL}/reset-password?" + urlencode({"token": token})
            html = f"""
              <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto">
                <p>Tap to reset your MyPinkAssistant password:</p>
                <p><a href="{link}">Reset password</a></p>
                <p style="color:#666;font-size:12px">This link expires in 30 minutes.</p>
              </div>
            """
            _send_resend_email(email.strip().lower(), "Reset your MyPinkAssistant password", html)
    except Exception as e:
        print("Forgot password send error:", e)

    return HTMLResponse(
        """
<!doctype html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Check your email</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto;background:#fff;color:#111;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}
  .card{width:min(460px,100%);border:1px solid #e8e8ee;border-radius:18px;padding:18px;box-shadow:0 10px 28px rgba(0,0,0,.07);text-align:center}
  h1{margin:0 0 6px;font-size:18px}
  p{margin:0;color:#666;font-size:13px;line-height:1.35}
  a{display:inline-block;margin-top:14px;color:#e91e63;text-decoration:none;font-weight:700}
</style>
</head>
<body>
  <div class="card">
    <h1>Check your email</h1>
    <p>If that email is registered, you’ll get a reset link in a moment.</p>
    <a href="/login">Back to login</a>
  </div>
</body>
</html>
"""
    )


# -------------------------
# Legal
# -------------------------
@app.get("/legal", response_class=HTMLResponse)
def legal_get(request: Request):
    return render_page("legal.html")


@app.get("/faq", response_class=HTMLResponse)
def faq_get(request: Request):
    return render_page("faq.html")


# -------------------------
# Reset password
# -------------------------
@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_get(token: str = ""):
    token = (token or "").strip()
    if not token:
        return RedirectResponse("/login", status_code=302)

    return HTMLResponse(
        f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Set new password • MyPinkAssistant</title>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto;background:#fff;color:#111;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}}
    .card{{width:min(460px,100%);border:1px solid #e8e8ee;border-radius:18px;padding:18px;box-shadow:0 10px 28px rgba(0,0,0,.07)}}
    h1{{margin:0 0 6px;text-align:center;font-size:18px}}
    p{{margin:0 0 12px;text-align:center;color:#666;font-size:13px;line-height:1.35}}
    label{{display:block;font-size:12px;color:#666;margin-top:12px}}
    input{{width:100%;margin-top:6px;padding:12px;border-radius:14px;border:1px solid #e8e8ee;font-size:14px}}
    button{{width:100%;margin-top:14px;padding:12px;border:0;border-radius:14px;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#e91e63,#c2185b);color:#fff}}
  </style>
</head>
<body>
  <div class="card">
    <h1>Set a new password</h1>
    <p>Choose a new password for your MyPinkAssistant account.</p>
    <form method="post" action="/reset-password">
      <input type="hidden" name="token" value="{token}"/>
      <label>New password</label>
      <input name="password" type="password" autocomplete="new-password" required />
      <label>Confirm password</label>
      <input name="password2" type="password" autocomplete="new-password" required />
      <button type="submit">Update password</button>
    </form>
  </div>
</body>
</html>
"""
    )


@app.post("/reset-password")
def reset_password_post(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    token = (token or "").strip()
    if not token:
        return HTMLResponse("Invalid reset token. <a href='/forgot'>Try again</a>.", status_code=400)

    if (password or "") != (password2 or ""):
        return HTMLResponse(
            "Passwords did not match. <a href='javascript:history.back()'>Go back</a>.",
            status_code=400,
        )

    if len(password) < 8:
        return HTMLResponse(
            "Password must be at least 8 characters. <a href='javascript:history.back()'>Go back</a>.",
            status_code=400,
        )

    th = _hash_token(token)
    now = int(time.time())

    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id, consultant_id, expires_at, used_at
        FROM password_resets
        WHERE token_hash={PH}
        ORDER BY id DESC
        LIMIT 1
        """,
        (th,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return HTMLResponse("That reset link is invalid. <a href='/forgot'>Try again</a>.", status_code=400)

    reset_id = _row_get(row, "id", None) or row[0]
    cid = _row_get(row, "consultant_id", None) or row[1]
    expires_at = _row_get(row, "expires_at", None) or row[2]
    used_at = _row_get(row, "used_at", None)

    try:
        expires_i = int(str(expires_at))
    except Exception:
        expires_i = 0

    if used_at is not None:
        conn.close()
        return HTMLResponse(
            "That reset link has already been used. <a href='/forgot'>Request a new one</a>.",
            status_code=400,
        )

    if now > expires_i:
        conn.close()
        return HTMLResponse(
            "That reset link has expired. <a href='/forgot'>Request a new one</a>.",
            status_code=400,
        )

    cur.execute(f"UPDATE password_resets SET used_at={USED_AT_NOW_SQL} WHERE id={PH}", (reset_id,))
    conn.commit()
    conn.close()

    set_consultant_password(int(cid), password)

    request.session.clear()
    return RedirectResponse("/login", status_code=302)


from fastapi.responses import HTMLResponse, RedirectResponse

@app.post("/onboard")
@limiter.limit("10/minute")
def onboard_post(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    password2: str = Form(""),
    language: str = Form("en"),
    intouch_username: str = Form(...),
    intouch_password: str = Form(...),
    ref: str = Form(""),
    agree_terms: str = Form(None),
):
    # normalize
    email = (email or "").strip().lower()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    intouch_username = (intouch_username or "").strip()

    def _err(msg: str) -> HTMLResponse:
        # history.back keeps what they typed in the browser
        return HTMLResponse(
            f"{msg}<br><br><a href='javascript:history.back()'>← Go back</a>",
            status_code=400,
        )

    # ---------------------------------------------------
    # If logged in, they should NOT be creating an account
    # ---------------------------------------------------
    cid = request.session.get("consultant_id")
    if cid:
        # If you want them to edit profile, send to /settings or /app
        return RedirectResponse("/app", status_code=302)

    # ---------------------------------------------------
    # New account validations
    # ---------------------------------------------------
    from urllib.parse import urlencode

    def _redirect_onboard_error(msg: str):
        q = urlencode({
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "intouch_username": intouch_username,
            "language": language,
            "ref": ref,
            "error": msg,
        })
        return RedirectResponse(f"/onboard?{q}", status_code=302)

    if password != password2:
        return _redirect_onboard_error("MyPinkAssistant.com passwords do not match.")

    if len(password or "") < 8:
        return _redirect_onboard_error("Password must be at least 8 characters.")

    if not agree_terms:
        return _redirect_onboard_error("You must agree to the Terms & Conditions.")

    # (Optional but recommended) require InTouch password too
    if len(intouch_password or "") < 1:
        return _err("Please enter your InTouch password.")

    from urllib.parse import urlencode

    # block duplicate emails
    existing_cid = _find_consultant_by_email(email)
    if existing_cid:
        q = urlencode(
            {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "intouch_username": intouch_username,
                "language": language,
                "error": "That email is already registered. Please <a href='/login'>log in</a> instead.",
            }
        )
        return RedirectResponse(f"/onboard?{q}", status_code=302)

    # ---------------------------------------------------
    # Create account
    # ---------------------------------------------------
    ok, msg, new_cid = create_consultant(email, password, language=language)
    if not ok:
        # e.g. "email already exists"
        return _err(msg)

    # <-- PUT IT HERE (right after success)
    ref_code = (ref or "").strip() or (request.session.get("referral_code") or "").strip()
    if ref_code:
        apply_referral(int(new_cid), ref_code)
        request.session.pop("referral_code", None)

    # Fill profile + InTouch
    update_profile_and_intouch(
        int(new_cid),
        email=email,
        first_name=first_name,
        last_name=last_name,
        language=language,
        intouch_username=intouch_username,
        intouch_password=intouch_password,
    )

    # Mark onboarding complete (so /onboard GET doesn't keep showing)
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"UPDATE consultants SET onboarding_complete=1 WHERE id={PH}",
            (int(new_cid),),
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    # Log them in
    request.session["consultant_id"] = int(new_cid)

    # NEW FLOW: now pay
    return RedirectResponse("/billing/start", status_code=302)


# -------------------------
# Protected app page
# -------------------------
@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant_full(cid)
    if not c or not is_profile_complete(c):
        return RedirectResponse("/onboard", status_code=302)
    
    # Billing Gate Here (use already-loaded consultant row)
    try:
        require_active_subscription_by_id(cid)  # Option A everywhere
    except PermissionError:
        return RedirectResponse(billing_redirect_for_cid(cid), status_code=302)

    index_path = WEB_DIR / "index.html"
    html = index_path.read_text(encoding="utf-8")

    # Admin button injection
    try:
        email = (c.get("email") or "").strip().lower()
        allowed = os.environ.get("MK_ADMIN_EMAILS", "")
        allowed_set = {e.strip().lower() for e in allowed.split(",") if e.strip()}
        is_admin = bool(allowed_set) and (email in allowed_set)
    except Exception:
        is_admin = False

    admin_btn = '<a class="btn" href="/admin">Admin</a>' if is_admin else ""

    html = html.replace("{{ADMIN_BUTTON}}", admin_btn)

    _lang = (c.get("language") or "en").strip().lower()
    _chat_placeholder = "Escribe un cliente o pedido…" if _lang == "es" else "Enter a customer or order…"
    html = html.replace("{{CHAT_PLACEHOLDER}}", _chat_placeholder)
    html = html.replace("{{CHAT_LANG}}", _lang)

    ui = get_ui_emergency()
    if ui["enabled"] and ui["message"]:
        banner = f"""
        <style>
        #ui-emergency-banner {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 99999;
            background: #fff3cd;
            color: #856404;
            padding: 14px 16px;
            text-align: center;
            font-weight: 600;
            border-bottom: 1px solid #ffeeba;
        }}

        /* chat-specific push-down */
        body {{
            padding-top: 70px !important;
        }}

        /* move the fixed topbar down */
        header.topbar {{
            top: 70px !important;
        }}

        /* push main layout down so it doesn't hide under header */
        main.layout {{
            padding-top: 70px !important;
        }}
        </style>

        <div id="ui-emergency-banner">{ui["message"]}</div>
        """

        if "<body" in html.lower():
            i = html.lower().find("<body")
            j = html.find(">", i) + 1
            html = html[:j] + banner + html[j:]

    return HTMLResponse(html)


# -------------------------
# Protected settings page
# -------------------------
@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant(cid)
    if not c:
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    lang = (c.get("language") or "en").strip().lower()
    if lang not in ("en", "es"):
        lang = "en"

    # ✅ referral code + link
    code = get_or_create_referral_code(int(cid))
    base = (os.getenv("APP_BASE_URL") or "").strip() or str(request.base_url).rstrip("/")
    referral_link = f"{base}/r/{code}"

    tax_rate_val = ""
    try:
        _tr = c.get("tax_rate")
        if _tr is not None:
            tax_rate_val = str(float(_tr))
            if tax_rate_val.endswith(".0"):
                tax_rate_val = tax_rate_val[:-2]
    except Exception:
        pass

    replaces = {
        "{{EMAIL}}": _esc(c.get("email") or ""),
        "{{INTOUCH_USERNAME}}": _esc(c.get("intouch_username") or ""),
        "{{LANG_VALUE}}": lang,
        "{{EN_ACTIVE}}": "active" if lang == "en" else "",
        "{{ES_ACTIVE}}": "active" if lang == "es" else "",

        # new:
        "{{REFERRAL_CODE}}": _esc(code),
        "{{REFERRAL_LINK}}": _esc(referral_link),

        "{{TAX_RATE}}": _esc(tax_rate_val),
    }
    return render_page("settings.html", replaces=replaces)


@app.post("/settings")
def settings_post(
    request: Request,
    language: str = Form("en"),
    intouch_username: str = Form(""),
    intouch_password: str = Form(""),
):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    pw_to_save = None if (intouch_password or "").strip() == "" else intouch_password
    update_settings(cid, language, intouch_username, pw_to_save)

    # If they saved InTouch creds, reset login failures and try to queue initial import
    if intouch_username.strip() and pw_to_save:
        with tx() as (conn, cur):
            cur.execute(
                f"""UPDATE consultants
                    SET consecutive_login_failures = 0,
                        last_login_failure_at = NULL,
                        initial_customer_import_queued = 0
                    WHERE id = {PH}""",
                (cid,),
            )
            maybe_queue_initial_customer_import(cur, consultant_id=cid)

    return RedirectResponse("/settings", status_code=302)

@app.post("/settings/tax-rate")
def settings_tax_rate(request: Request, tax_rate: str = Form("")):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"ok": False}, status_code=401)
    tax_rate = (tax_rate or "").strip()
    if tax_rate == "":
        rate_val = None
    else:
        try:
            rate_val = float(tax_rate)
            if rate_val < 0 or rate_val > 100:
                return JSONResponse({"ok": False, "error": "Tax rate must be between 0 and 100."})
        except ValueError:
            return JSONResponse({"ok": False, "error": "Invalid tax rate."})
    with tx() as (conn, cur):
        cur.execute(f"UPDATE consultants SET tax_rate = {PH} WHERE id = {PH}", (rate_val, cid))
    return JSONResponse({"ok": True})


@app.post("/settings/language")
def settings_language(request: Request, language: str = Form("en")):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"ok": False}, status_code=401)
    language = language.strip().lower()
    if language not in ("en", "es"):
        language = "en"
    with tx() as (conn, cur):
        cur.execute(f"UPDATE consultants SET language = {PH} WHERE id = {PH}", (language, cid))
    return JSONResponse({"ok": True})

@app.get("/inventory/print", response_class=HTMLResponse)
def inventory_print(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant(cid)
    if not c:
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    from inventory_store import list_inventory
    from mk_chat_core import load_catalog, get_catalog_path_for_language
    from db import tx
    from datetime import date

    consultant_name = f"{(c.get('first_name') or '').strip()} {(c.get('last_name') or '').strip()}".strip()
    lang = (c.get("language") or "en").strip().lower()
    catalog_path = get_catalog_path_for_language(lang)
    catalog = load_catalog(catalog_path)

    with tx() as (conn, cur):
        inv_rows = list_inventory(cur, consultant_id=int(cid))

    # Build lookup: sku -> inventory row
    inv_by_sku = {str(r.get("sku") or "").strip(): r for r in inv_rows}

    today = date.today().strftime("%B %d, %Y")

    # Build table rows for the full catalog
    rows_html = []
    for item in catalog:
        sku = (item.get("sku") or "").strip()
        name = _esc(item.get("product_name") or "")
        retail = item.get("price")
        retail_txt = f"${retail:.2f}" if isinstance(retail, (int, float)) else "—"

        inv = inv_by_sku.get(sku) or {}
        qty = inv.get("qty_on_hand")
        threshold = inv.get("low_stock_threshold")

        qty_txt = str(int(qty)) if qty is not None else ""
        threshold_txt = str(int(threshold)) if threshold is not None else ""

        low = qty is not None and threshold is not None and int(qty) < int(threshold)
        row_class = ' class="low"' if low else ""
        on_hand_class = ' class="low-cell"' if low else ""

        qty_val = int(qty) if qty is not None else ""
        threshold_val = int(threshold) if threshold is not None else ""
        sku_esc = _esc(sku)

        retail_val = (retail * int(qty)) if (isinstance(retail, (int, float)) and qty is not None and int(qty) > 0) else 0.0

        rows_html.append(
            f'<tr{row_class} data-has-qty="{1 if qty else 0}" data-sku="{sku_esc}" data-retail="{retail_val:.2f}">'
            f"<td>{name}</td>"
            f'<td class="sku-cell">{sku_esc}</td>'
            f"<td>{retail_txt}</td>"
            f'<td{on_hand_class}>'
            f'<span class="dv">{qty_txt}</span>'
            f'<input class="ev inv-input hidden" type="number" min="0" data-field="qty" value="{qty_val}">'
            f"</td>"
            f"<td>"
            f'<span class="dv">{threshold_txt}</span>'
            f'<input class="ev inv-input hidden" type="number" min="0" data-field="par" value="{threshold_val}">'
            f"</td>"
            f"</tr>"
        )

    table_rows = "\n".join(rows_html)
    consultant_esc = _esc(consultant_name)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Inventory Report — {consultant_esc}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; font-size: 13px; color: #111; margin: 0; padding: 20px; }}
    h1 {{ font-size: 18px; margin: 0 0 4px; }}
    .meta {{ color: #666; font-size: 12px; margin-bottom: 16px; }}
    .controls {{ margin-bottom: 14px; display: flex; gap: 10px; align-items: center; }}
    .controls label {{ font-size: 13px; cursor: pointer; }}
    .btn-print {{ background: #d63384; color: #fff; border: none; padding: 7px 18px; border-radius: 8px; font-size: 13px; cursor: pointer; font-weight: 600; }}
    .btn-print:hover {{ background: #b02a6f; }}
    .inv-input {{ width: 60px; padding: 3px 6px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; }}
    table {{ width: auto; border-collapse: collapse; white-space: nowrap; }}
    th {{ background: #f5f5f7; text-align: left; padding: 7px 10px; font-size: 12px; border-bottom: 2px solid #ddd; }}
    td {{ padding: 6px 10px; border-bottom: 1px solid #eee; }}
    tr.low td.low-cell {{ color: #c0392b; font-weight: 700; }}
    tr.low {{ background: #fff5f5; }}
    .hidden {{ display: none; }}
    .sku-cell {{ color: #888; font-size: 11px; }}
    .summary-bar {{
      position: sticky; top: 0; z-index: 10;
      display: inline-block;
      background: #fff8fb; border: 1px solid #f0d0e0; border-radius: 8px;
      padding: 10px 16px; margin-bottom: 14px;
      font-size: 14px;
    }}
    .summary-bar .grand-total {{ font-weight: 700; color: #d63384; }}
    @media print {{
      .controls {{ display: none; }}
      body {{ padding: 10px; }}
      tr.low td.low-cell {{ color: #c0392b; }}
      .summary-bar {{ position: static; }}
    }}
  </style>
</head>
<body>
  <h1>Inventory Report — {consultant_esc}</h1>
  <div class="meta">{today}</div>
  <div class="controls">
    <label>
      <input type="radio" name="view" value="all" checked id="view-all"> Full Catalog
    </label>
    <label>
      <input type="radio" name="view" value="onhand" id="view-onhand"> On Hand Only
    </label>
    <label>
      <input type="radio" name="view" value="enter" id="view-enter"> Enter Inventory
    </label>
    <button class="btn-print" id="btn-print">Print / Save PDF</button>
  </div>
  <div class="summary-bar" id="summary-bar">
    Total Retail Value on Shelf: <span class="grand-total" id="grand-total">$0.00</span>
  </div>
  <table id="inv-table">
    <thead>
      <tr>
        <th>Product</th>
        <th>SKU</th>
        <th>Retail</th>
        <th>On Hand</th>
        <th>Par</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
  <script src="/web/print.js"></script>
</body>
</html>"""

    return HTMLResponse(html)


@app.post("/inventory/bulk-save")
async def inventory_bulk_save(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"ok": False}, status_code=401)

    from inventory_store import upsert_inventory_quantity
    from db import tx

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request"}, status_code=400)

    with tx() as (conn, cur):
        for item in (data or []):
            sku = (item.get("sku") or "").strip()
            if not sku:
                continue
            qty = item.get("qty")
            par = item.get("par")
            if qty is None and par is None:
                continue
            set_qty = int(qty) if qty is not None and str(qty).strip() != "" else None
            set_par = int(par) if par is not None and str(par).strip() != "" else None
            upsert_inventory_quantity(
                cur,
                consultant_id=int(cid),
                sku=sku,
                set_qty=set_qty,
                low_stock_threshold=set_par,
            )

    return JSONResponse({"ok": True})


@app.post("/import-customers")
def import_customers(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant_full(cid) or {}
    try:
        require_active_subscription(c)
    except PermissionError:
        return RedirectResponse(billing_redirect_for_cid(cid), status_code=302)

    # Cooldown: block if a queued/running job exists, or any import finished in the last 5 minutes
    from db import tx as _tx
    from db import is_postgres as _isp
    _PH = "%s" if _isp() else "?"
    with _tx() as (_conn, _cur):
        if _isp():
            _cur.execute(
                f"""
                SELECT 1 FROM jobs
                WHERE consultant_id = {_PH}
                  AND type = 'IMPORT_CUSTOMERS'
                  AND (
                    status IN ('queued', 'running')
                    OR (status IN ('done', 'failed') AND finished_at >= NOW() - INTERVAL '5 minutes')
                  )
                LIMIT 1
                """,
                (cid,),
            )
        else:
            _cur.execute(
                f"""
                SELECT 1 FROM jobs
                WHERE consultant_id = {_PH}
                  AND type = 'IMPORT_CUSTOMERS'
                  AND (
                    status IN ('queued', 'running')
                    OR (status IN ('done', 'failed') AND finished_at >= datetime('now', '-5 minutes'))
                  )
                LIMIT 1
                """,
                (cid,),
            )
        if _cur.fetchone():
            return RedirectResponse("/app?notice=import_cooldown", status_code=302)

    insert_job("IMPORT_CUSTOMERS", {}, consultant_id=cid)
    return RedirectResponse("/app", status_code=302)


@app.post("/import-customers-api")
def import_customers_api(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant_full(cid) or {}
    try:
        require_active_subscription(c)
    except PermissionError:
        return RedirectResponse(billing_redirect_for_cid(cid), status_code=302)

    from db import tx as _tx
    from db import is_postgres as _isp
    _PH = "%s" if _isp() else "?"
    with _tx() as (_conn, _cur):
        if _isp():
            _cur.execute(
                f"""
                SELECT 1 FROM jobs
                WHERE consultant_id = {_PH}
                  AND type = 'IMPORT_CUSTOMERS_API'
                  AND (
                    status IN ('queued', 'running')
                    OR (status IN ('done', 'failed') AND finished_at >= NOW() - INTERVAL '5 minutes')
                  )
                LIMIT 1
                """,
                (cid,),
            )
        else:
            _cur.execute(
                f"""
                SELECT 1 FROM jobs
                WHERE consultant_id = {_PH}
                  AND type = 'IMPORT_CUSTOMERS_API'
                  AND (
                    status IN ('queued', 'running')
                    OR (status IN ('done', 'failed') AND finished_at >= datetime('now', '-5 minutes'))
                  )
                LIMIT 1
                """,
                (cid,),
            )
        if _cur.fetchone():
            return RedirectResponse("/app?notice=import_cooldown", status_code=302)

    insert_job("IMPORT_CUSTOMERS_API", {}, consultant_id=cid)
    return RedirectResponse("/app", status_code=302)


@app.post("/import-order-history")
def import_order_history_route(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant_full(cid) or {}
    try:
        require_active_subscription(c)
    except PermissionError:
        return RedirectResponse(billing_redirect_for_cid(cid), status_code=302)

    insert_job("IMPORT_ORDER_HISTORY", {}, consultant_id=cid)
    return RedirectResponse("/app", status_code=302)


@app.post("/import-inventory-orders")
def import_inventory_orders_route(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    c = get_consultant_full(cid) or {}
    try:
        require_active_subscription(c)
    except PermissionError:
        return RedirectResponse(billing_redirect_for_cid(cid), status_code=302)

    insert_job("IMPORT_INVENTORY_ORDERS", {"date_range": "days90"}, consultant_id=cid)
    return RedirectResponse("/app", status_code=302)


@app.post("/reset-inventory-import-history")
def reset_inventory_import_history(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    from inventory_import_store import ensure_import_table
    from db import connect, is_postgres
    ensure_import_table()
    PH = "%s" if is_postgres() else "?"
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM inventory_intouch_imports WHERE consultant_id = {PH}",
            (int(cid),),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/settings", status_code=302)


# -------------------------
# Follow-up API
# -------------------------
@app.post("/followup/complete")
async def followup_complete(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"ok": False}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)

    card_type = data.get("card_type", "order")
    from db import tx

    if card_type == "birthday":
        customer_id = data.get("customer_id")
        if not customer_id:
            return JSONResponse({"ok": False}, status_code=400)
        from followup_store import complete_birthday_followup
        with tx() as (conn, cur):
            ok = complete_birthday_followup(cur, consultant_id=int(cid), customer_id=int(customer_id))
    else:
        order_id = data.get("order_id")
        followup_window = data.get("followup_window")
        if not order_id or not followup_window:
            return JSONResponse({"ok": False}, status_code=400)
        from followup_store import complete_followup
        with tx() as (conn, cur):
            ok = complete_followup(cur, consultant_id=int(cid), order_id=int(order_id), followup_window=int(followup_window))
    return JSONResponse({"ok": ok})


# -------------------------
# Chat + Jobs API (protected)
# -------------------------
@app.post("/chat")
async def chat(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"reply": "Please log in."}, status_code=401)

    c = get_consultant_full(cid) or {}
    try:
        require_active_subscription(c)
    except PermissionError:
        return JSONResponse({"reply": "Billing inactive. Please subscribe to continue."}, status_code=402)

    data = await request.json()
    message = (data.get("message") or "").strip()

    try:
        reply_obj = engine.handle_message(message, consultant_id=cid)
        return {"reply": reply_obj.reply}
    except Exception as e:
        logging.error("Chat handler error: %s", repr(e))
        return {"reply": "Something went wrong. Please try again."}


@app.get("/jobs")
def jobs(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"jobs": []}, status_code=401)
    
    c = get_consultant_full(cid) or {}
    try:
        require_active_subscription(c)
    except PermissionError:
        return JSONResponse({"jobs": [], "error": "Billing inactive"}, status_code=402)

    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id, type, status, error, status_msg, payload_json
        FROM jobs
        WHERE consultant_id = {PH}
        ORDER BY id DESC
        LIMIT 25
        """,
        (cid,),
    )
    rows = cur.fetchall()
    conn.close()

    out = []
    for r in rows:
        payload_raw = _row_get(r, "payload_json", None) if _row_get(r, "payload_json", None) is not None else r[5]

        try:
            payload = json.loads(payload_raw or "{}")
        except Exception:
            payload = {}

        out.append(
            {
                "id": _row_get(r, "id", None) if _row_get(r, "id", None) is not None else r[0],
                "type": _row_get(r, "type", "") if _row_get(r, "type", None) is not None else r[1],
                "status": _row_get(r, "status", "") if _row_get(r, "status", None) is not None else r[2],
                "error": _row_get(r, "error", "") if _row_get(r, "error", None) is not None else (r[3] or ""),
                "status_msg": _row_get(r, "status_msg", "") if _row_get(r, "status_msg", None) is not None else (r[4] or ""),
                "payload": payload,  # ✅ THIS IS THE KEY ADD
            }
        )
    failures = int((c.get("consecutive_login_failures") or 0))
    return {"jobs": out, "creds_failed": failures >= 1}

# -------------------------
# Admin diagnostics (protected)
# -------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_diagnostics(request: Request):
    # ✅ Admin gate
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)
    
    ui = get_ui_emergency()
    em_checked = "checked" if ui["enabled"] else ""
    em_msg = ui["message"].replace('"', "&quot;")
    queue_paused = (get_system_setting("queue_paused", "0") or "0").strip() == "1"

    CT = ZoneInfo("America/Chicago")

    def _to_ct(val):
        """
        Convert DB timestamp to America/Chicago for display.
        Handles:
          - datetime (aware or naive)
          - sqlite strings: "YYYY-MM-DD HH:MM:SS"
          - iso strings with 'T' or 'Z'
        Returns None if not parseable.
        """
        if val is None:
            return None

        if isinstance(val, datetime):
            dt = val
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(CT)

        s = str(val).strip()
        if not s:
            return None

        try:
            s2 = s.replace("Z", "+00:00")

            # sqlite "YYYY-MM-DD HH:MM:SS" (assume UTC)
            if " " in s2 and "T" not in s2 and "+" not in s2:
                dt = datetime.fromisoformat(s2.replace(" ", "T"))
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(CT)

            dt = datetime.fromisoformat(s2)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(CT)
        except Exception:
            return None

    def _fmt_ct(val):
        dt = _to_ct(val)
        if not dt:
            return ""
        # Cross-platform: avoid %-I (not supported everywhere)
        s = dt.strftime("%Y-%m-%d %I:%M:%S %p CT")
        return s.replace(" 0", " ")  # remove leading zero in hour

    conn = _conn()
    cur = conn.cursor()

    # 1) Job counts
    cur.execute("SELECT status, COUNT(*) AS n FROM jobs WHERE status != 'failed' OR COALESCE(admin_hidden, false) = false GROUP BY status")
    counts = cur.fetchall()

    counts_map = {}
    for r in counts:
        status = _row_get(r, "status", None) if _row_get(r, "status", None) is not None else r[0]
        n = _row_get(r, "n", None) if _row_get(r, "n", None) is not None else r[1]
        counts_map[str(status)] = int(n)

    # 2) Oldest queued / running timestamps
    cur.execute("SELECT MIN(created_at) FROM jobs WHERE status='queued'")
    oldest_queued = cur.fetchone()
    cur.execute("SELECT MIN(started_at) FROM jobs WHERE status='running'")
    oldest_running = cur.fetchone()

    oldest_queued_val = oldest_queued[0] if oldest_queued else None
    oldest_running_val = oldest_running[0] if oldest_running else None

    # 3) Running jobs
    cur.execute(
        """
        SELECT id, consultant_id, type, attempts, claimed_by, claimed_at, started_at
        FROM jobs
        WHERE status='running'
        ORDER BY started_at ASC NULLS LAST, id ASC
        LIMIT 50
        """
        if is_postgres()
        else
        """
        SELECT id, consultant_id, type, attempts, claimed_by, claimed_at, started_at
        FROM jobs
        WHERE status='running'
        ORDER BY started_at ASC, id ASC
        LIMIT 50
        """
    )
    running = cur.fetchall()

    # 4) DONE jobs (last 15) — exclude nightly scheduler syncs, show onboard/manual ones
    cur.execute(
        """
        SELECT id, consultant_id, type, status_msg, finished_at
        FROM jobs
        WHERE status='done'
          AND NOT (
            type IN ('IMPORT_CUSTOMERS', 'IMPORT_INVENTORY_ORDERS', 'FULL_SYNC')
            AND payload_json LIKE '%scheduler%'
          )
        ORDER BY id DESC
        LIMIT 15
        """
    )
    done = cur.fetchall()

    # 5) FAILED jobs (last 15)
    cur.execute(
        """
        SELECT id, consultant_id, type, error, finished_at
        FROM jobs
        WHERE status='failed' AND COALESCE(admin_hidden, false) = false
        ORDER BY id DESC
        LIMIT 15
        """
    )
    failed = cur.fetchall()

    # 6) Locks
    try:
        cur.execute("SELECT consultant_id, locked_by, locked_at FROM consultant_locks ORDER BY locked_at DESC")
        locks = cur.fetchall()
    except Exception:
        locks = []

    conn.close()

    def fmt_row(row, keys):
        out = {}
        for i, k in enumerate(keys):
            v = _row_get(row, k, None)
            if v is None:
                try:
                    v = row[i]
                except Exception:
                    v = None
            out[k] = v
        return out

    running_rows = [fmt_row(r, ["id","consultant_id","type","attempts","claimed_by","claimed_at","started_at"]) for r in running]
    done_rows = [fmt_row(r, ["id","consultant_id","type","status_msg","finished_at"]) for r in done]
    failed_rows = [fmt_row(r, ["id","consultant_id","type","error","finished_at"]) for r in failed]
    lock_rows = [fmt_row(r, ["consultant_id","locked_by","locked_at"]) for r in locks]

    # -------------------------
    # Consultant display lookup (ID -> "First Last" + muted email)
    # -------------------------
    conn2 = _conn()
    cur2 = conn2.cursor()
    cur2.execute("SELECT id, first_name, last_name, email, referred_by_consultant_id, created_at FROM consultants ORDER BY id ASC")
    consultant_rows = cur2.fetchall()
    conn2.close()

    consultants_html = {}
    consultant_names = {}  # id -> "First Last" for referrer lookup
    consultant_data = []   # for the consultants table

    for r in consultant_rows:
        cid = _row_get(r, "id", None) if _row_get(r, "id", None) is not None else r[0]
        fn = (_row_get(r, "first_name", "") if _row_get(r, "first_name", None) is not None else (r[1] or "")).strip()
        ln = (_row_get(r, "last_name", "") if _row_get(r, "last_name", None) is not None else (r[2] or "")).strip()
        em = (_row_get(r, "email", "") if _row_get(r, "email", None) is not None else (r[3] or "")).strip()
        ref_by = _row_get(r, "referred_by_consultant_id", None)
        if ref_by is None:
            try: ref_by = r[4]
            except Exception: ref_by = None
        created = _row_get(r, "created_at", None)
        if created is None:
            try: created = r[5]
            except Exception: created = None

        name = f"{fn} {ln}".strip() or "Unknown"
        email_html = f"<div class='consultant-email'>{em}</div>" if em else ""
        consultants_html[int(cid)] = f"<div class='consultant-name'>{name}</div>{email_html}"
        consultant_names[int(cid)] = name
        consultant_data.append({"id": int(cid), "name": name, "email": em, "ref_by": ref_by, "created_at": created})

    def consultant_cell(cid_val):
        try:
            cid_int = int(cid_val)
        except Exception:
            return "<div class='consultant-name'>Unknown</div>"
        return consultants_html.get(cid_int, "<div class='consultant-name'>Unknown</div>")

    referred = [c for c in consultant_data if c["ref_by"]][-15:][::-1]
    consultant_rows_html = ""
    for c in referred:
        ref = consultant_names.get(int(c["ref_by"]), "Unknown")
        consultant_rows_html += (
            "<tr>"
            "<td>" + str(c["name"]) + "</td>"
            "<td style='font-size:12px;color:#666'>" + str(c["email"]) + "</td>"
            "<td>" + ref + "</td>"
            "<td>" + (_fmt_ct(c["created_at"]) or "") + "</td>"
            "</tr>"
        )
    if not consultant_rows_html:
        consultant_rows_html = "<tr><td colspan='4' class='muted'>No referred consultants yet.</td></tr>"

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Admin • Diagnostics</title>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto;background:#fff;color:#111;margin:0}}
    .wrap{{max-width:1100px;margin:0 auto;padding:22px 18px}}
    h1{{margin:0 0 6px;font-size:20px}}
    .muted{{color:#666;font-size:13px}}
    .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}}
    .card{{border:1px solid #e8e8ee;border-radius:14px;padding:12px;background:#fafafa}}
    .k{{font-size:12px;color:#666}}
    .v{{font-size:20px;font-weight:800;margin-top:4px}}
    table{{width:100%;border-collapse:collapse;margin-top:12px}}
    th,td{{border-bottom:1px solid #eee;padding:8px 6px;font-size:13px;vertical-align:top}}
    th{{text-align:left;color:#666;font-weight:700}}
    code{{font-size:12px;}}
    .pill{{display:inline-block;padding:2px 8px;border-radius:999px;background:#f1f1f1;font-size:12px;color:#555}}
    .row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}
    a{{color:#e91e63;text-decoration:none;font-weight:700}}
    @media (max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}}}

    /* Consultant cell */
    .consultant-name{{font-weight:700}}
    .consultant-email{{color:#666;font-size:12px}}

    /* Admin buttons */
    .adminBtn{{
      padding:8px 14px;
      border-radius:10px;
      border:1px solid #ddd;
      background:#fff;
      color:#111;
      font-weight:600;
      cursor:pointer;
      min-width:140px;
    }}
    .adminBtn:hover{{ background:#f5f5f5; }}
    .adminBtn.danger{{
      border-color:#f5c2c2;
      background:#fff5f5;
      color:#b91c1c;
    }}
    
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Admin Diagnostics</h1>
    <div class="muted">Jobs + locks overview for troubleshooting. (Private)</div>

    <div class="row">
      <span class="pill">Oldest queued (CT): {_fmt_ct(oldest_queued_val) or ""}</span>
      <span class="pill">Oldest running (CT): {_fmt_ct(oldest_running_val) or ""}</span>
    </div>

    <!-- Admin action buttons -->
    <div class="row" style="margin-top:14px">
    <form method="post" action="/admin/clear-locks">
        <button type="submit" class="adminBtn">Clear All Locks</button>
    </form>

    <form method="post" action="/admin/fail-running">
        <button type="submit" class="adminBtn danger">Fail All Running Jobs</button>
    </form>

    <form method="post" action="/admin/clear-failed">
        <button type="submit" class="adminBtn">Clear Failed Jobs</button>
    </form>

    <form method="post" action="/admin/pause-queue">
        <button type="submit" class="adminBtn {'danger' if queue_paused else ''}">{'Unpause Queue ▶️' if queue_paused else 'Pause Queue ⏸'}</button>
    </form>
    </div>
    
    <h2 style="margin:20px 0 6px;font-size:16px">Emergency UI Banner</h2>
    <div class="card">
    <form method="post" action="/admin/ui-emergency">

        <label style="display:flex;gap:8px;align-items:center">
        <input type="checkbox" name="enabled" value="1" {em_checked} />
        <span style="font-weight:700">Enable emergency banner</span>
        </label>

        <label style="display:block;font-size:12px;color:#666;margin-top:10px">
        Banner Message
        </label>

        <input
        name="message"
        value="{em_msg}"
        placeholder="Example: We’re performing maintenance. Chat may be delayed."
        style="width:100%;margin-top:6px;padding:10px;border-radius:10px;border:1px solid #ddd;"
        />

        <button type="submit" class="adminBtn" style="margin-top:12px">
        Save Banner
        </button>

    </form>
    </div>

    <div class="cards">
      <div class="card"><div class="k">Queued</div><div class="v">{counts_map.get("queued",0)}</div></div>
      <div class="card"><div class="k">Running</div><div class="v">{counts_map.get("running",0)}</div></div>
      <div class="card"><div class="k">Failed</div><div class="v">{counts_map.get("failed",0)}</div></div>
      <div class="card"><div class="k">Done</div><div class="v">{counts_map.get("done",0)}</div></div>
    </div>

    <h2 style="margin:16px 0 6px;font-size:16px">Running jobs</h2>
    <table>
      <tr>
        <th>id</th><th>consultant</th><th>type</th><th>attempts</th><th>claimed_by</th><th>started (CT)</th>
      </tr>
      {''.join([f"<tr><td>{r['id']}</td><td>{consultant_cell(r['consultant_id'])}</td><td>{r['type']}</td><td>{r['attempts']}</td><td>{r['claimed_by']}</td><td>{_fmt_ct(r['started_at'])}</td></tr>" for r in running_rows]) or "<tr><td colspan='6' class='muted'>No running jobs.</td></tr>"}
    </table>

    <!-- ✅ Locks moved here: under Running, above Completed -->
    <h2 style="margin:16px 0 6px;font-size:16px">Consultant locks</h2>
    <table>
      <tr>
        <th>consultant</th><th>locked_by</th><th>locked_at (CT)</th>
      </tr>
      {''.join([f"<tr><td>{consultant_cell(r['consultant_id'])}</td><td>{r['locked_by']}</td><td>{_fmt_ct(r['locked_at'])}</td></tr>" for r in lock_rows]) or "<tr><td colspan='3' class='muted'>No locks.</td></tr>"}
    </table>

    <!-- ✅ Completed above Failed -->
    <h2 style="margin:16px 0 6px;font-size:16px">Completed (last 15)</h2>
    <table>
      <tr>
        <th>id</th><th>consultant</th><th>type</th><th>message</th><th>finished (CT)</th>
      </tr>
      {''.join([f"<tr><td>{r['id']}</td><td>{consultant_cell(r['consultant_id'])}</td><td>{r['type']}</td><td>{(r['status_msg'] or '')}</td><td>{_fmt_ct(r['finished_at'])}</td></tr>" for r in done_rows]) or "<tr><td colspan='5' class='muted'>No completed jobs.</td></tr>"}
    </table>

    <h2 style="margin:16px 0 6px;font-size:16px">Recent failed (last 15)</h2>
    <table>
      <tr>
        <th>id</th><th>consultant</th><th>type</th><th>error</th><th>finished (CT)</th>
      </tr>
      {''.join([f"<tr><td>{r['id']}</td><td>{consultant_cell(r['consultant_id'])}</td><td>{r['type']}</td><td><details><summary><code>{((r['error'] or '').splitlines() or [''])[0][:80]}</code></summary><code>{(r['error'] or '')[:500]}</code></details></td><td>{_fmt_ct(r['finished_at'])}</td></tr>" for r in failed_rows]) or "<tr><td colspan='5' class='muted'>No failed jobs.</td></tr>"}
    </table>

    <h2 style=”margin:16px 0 6px;font-size:16px”>Referred Consultants (last 15)</h2>
    <table>
      <tr>
        <th>name</th><th>email</th><th>referred by</th><th>joined (CT)</th>
      </tr>
      {consultant_rows_html}
    </table>

    <div style=”margin-top:16px” class=”muted”>
      Tip: if you ever see “running” jobs older than ~15 minutes, the worker likely crashed mid-run.
    </div>

    <div style="margin-top:10px">
      <a href="/app">← Back to app</a>
    </div>
  </div>
</body>
</html>
"""
    return HTMLResponse(html)


# -------------------------
# Admin actions (protected)
# -------------------------
@app.post("/admin/clear-locks")
def admin_clear_locks(request: Request):
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM consultant_locks")
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/fail-running")
def admin_fail_all_running(request: Request):
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    conn = _conn()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute(
                """
                UPDATE jobs
                SET status='failed',
                    status_msg='Failed ❌',
                    error=CASE
                        WHEN COALESCE(error,'') = '' THEN 'admin: failed running jobs'
                        ELSE LEFT(error,1800) || ' | admin: failed running jobs'
                    END,
                    finished_at=NOW()
                WHERE status='running'
                """
            )
        else:
            cur.execute(
                """
                UPDATE jobs
                SET status='failed',
                    status_msg='Failed ❌',
                    error=CASE
                        WHEN IFNULL(error,'') = '' THEN 'admin: failed running jobs'
                        ELSE SUBSTR(error,1,1800) || ' | admin: failed running jobs'
                    END,
                    finished_at=datetime('now')
                WHERE status='running'
                """
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/admin", status_code=302)

@app.post("/admin/clear-failed")
def admin_clear_failed(request: Request):
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE jobs SET admin_hidden=true WHERE status='failed'")
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/admin", status_code=302)

@app.post("/admin/pause-queue")
def admin_pause_queue(request: Request):
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    current = (get_system_setting("queue_paused", "0") or "0").strip()
    set_system_setting("queue_paused", "0" if current == "1" else "1")
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/ui-emergency")
def admin_ui_emergency_post(
    request: Request,
    enabled: str = Form(None),
    message: str = Form(""),
):
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    is_enabled = enabled == "1"
    set_ui_emergency(is_enabled, message)

    return RedirectResponse("/admin", status_code=302)

# -------------------------
# Reset chat memory (protected)
# -------------------------
@app.post("/reset")
def reset(request: Request):
    """
    Reset chat memory for THIS consultant (clears pending + last_customer).
    """
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"ok": False}, status_code=401)

    save_session_state({"last_customer": None, "pending": None}, session_id=int(cid))
    return {"ok": True}
