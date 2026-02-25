##update app.py for admin page

# app.py
import os
import time
import secrets
import hashlib
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
from dotenv import load_dotenv

from db import connect, is_postgres
from db import get_system_setting, set_system_setting
from mk_chat_core import MKChatEngine, save_session_state
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

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
PAGES_DIR = BASE_DIR / "pages"

app = FastAPI()
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
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render_page("landing.html")


from fastapi.responses import RedirectResponse

@app.get("/r/{code}")
def referral_landing(request: Request, code: str):
    """
    Referral link landing.
    Stores referral code in session, then sends them to onboarding.
    Example share link: https://mypinkassistant.com/r/ABC123
    """
    code = (code or "").strip()
    if code:
        request.session["referral_code"] = code
    return RedirectResponse("/onboard", status_code=302)

@app.get("/splash.html", response_class=HTMLResponse)
def splash(request: Request):
    return render_page("splash.html")

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
def forgot_post(email: str = Form(...)):
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
    
    print("[APP] c keys:", list((c or {}).keys()))
    print("[APP] c billing_status:", (c or {}).get("billing_status"))
    
    # Billing Gate Here (use already-loaded consultant row)
    try:
        require_active_subscription_by_id(cid)  # Option A everywhere
    except PermissionError:
        return RedirectResponse(billing_redirect_for_cid(cid), status_code=302)

    index_path = WEB_DIR / "index.html"
    html = index_path.read_text(encoding="utf-8")

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
    referral_link = f"{base}/onboard?ref={code}"

    replaces = {
        "{{EMAIL}}": (c.get("email") or ""),
        "{{INTOUCH_USERNAME}}": (c.get("intouch_username") or ""),
        "{{LANG_VALUE}}": lang,
        "{{EN_ACTIVE}}": "active" if lang == "en" else "",
        "{{ES_ACTIVE}}": "active" if lang == "es" else "",

        # new:
        "{{REFERRAL_CODE}}": code,
        "{{REFERRAL_LINK}}": referral_link,
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
    return RedirectResponse("/settings", status_code=302)


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
        return {"reply": f"❌ Server error: {e}"}


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
        SELECT id, type, status, error, status_msg
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
        out.append(
            {
                "id": _row_get(r, "id", None) if _row_get(r, "id", None) is not None else r[0],
                "type": _row_get(r, "type", "") if _row_get(r, "type", None) is not None else r[1],
                "status": _row_get(r, "status", "") if _row_get(r, "status", None) is not None else r[2],
                "error": _row_get(r, "error", "") if _row_get(r, "error", None) is not None else (r[3] or ""),
                "status_msg": _row_get(r, "status_msg", "") if _row_get(r, "status_msg", None) is not None else (r[4] or ""),
            }
        )
    return {"jobs": out}

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
    cur.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
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

    # 4) DONE jobs (last 15)
    cur.execute(
        """
        SELECT id, consultant_id, type, status_msg, finished_at
        FROM jobs
        WHERE status='done'
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
        WHERE status='failed'
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
    cur2.execute("SELECT id, first_name, last_name, email FROM consultants")
    consultant_rows = cur2.fetchall()
    conn2.close()

    consultants_html = {}
    for r in consultant_rows:
        cid = _row_get(r, "id", None) if _row_get(r, "id", None) is not None else r[0]
        fn = (_row_get(r, "first_name", "") if _row_get(r, "first_name", None) is not None else (r[1] or "")).strip()
        ln = (_row_get(r, "last_name", "") if _row_get(r, "last_name", None) is not None else (r[2] or "")).strip()
        em = (_row_get(r, "email", "") if _row_get(r, "email", None) is not None else (r[3] or "")).strip()

        name = f"{fn} {ln}".strip() or "Unknown"
        email_html = f"<div class='consultant-email'>{em}</div>" if em else ""
        consultants_html[int(cid)] = f"<div class='consultant-name'>{name}</div>{email_html}"

    def consultant_cell(cid_val):
        try:
            cid_int = int(cid_val)
        except Exception:
            return "<div class='consultant-name'>Unknown</div>"
        return consultants_html.get(cid_int, "<div class='consultant-name'>Unknown</div>")

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
    code{{font-size:12px}}
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
      font-weight:600;
      cursor:pointer;
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
      {''.join([f"<tr><td>{r['id']}</td><td>{consultant_cell(r['consultant_id'])}</td><td>{r['type']}</td><td><code>{(r['error'] or '')[:300]}</code></td><td>{_fmt_ct(r['finished_at'])}</td></tr>" for r in failed_rows]) or "<tr><td colspan='5' class='muted'>No failed jobs.</td></tr>"}
    </table>

    <div style="margin-top:16px" class="muted">
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
