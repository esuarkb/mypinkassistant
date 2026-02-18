##update app.py for admin page

# app.py
import os
import time
import secrets
import hashlib
import requests
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from db import connect, is_postgres
from mk_chat_core import MKChatEngine, save_session_state

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
    if replaces:
        for k, v in replaces.items():
            html = html.replace(k, v)
    return HTMLResponse(html)


# Create the chat engine once (loads catalog once)
engine = MKChatEngine()


# -------------------------
# Public pages
# -------------------------
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render_page("landing.html")


@app.get("/splash.html", response_class=HTMLResponse)
def splash(request: Request):
    return render_page("splash.html")


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    cid = request.session.get("consultant_id")
    if cid:
        c = get_consultant_full(int(cid))
        if not is_profile_complete(c):
            return RedirectResponse("/onboard", status_code=302)
        return RedirectResponse("/app", status_code=302)
    return render_page("login.html")


@app.post("/login")
def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    cid = authenticate(email, password)
    if not cid:
        return HTMLResponse("Login failed. <a href='/login'>Try again</a>.", status_code=401)

    request.session["consultant_id"] = int(cid)

    c = get_consultant_full(int(cid))
    if not is_profile_complete(c):
        return RedirectResponse("/onboard", status_code=302)

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


# -------------------------
# Onboarding (public; can be accessed without login)
# -------------------------
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
):
    cid = request.session.get("consultant_id")

    # CASE A: Already logged in → UPDATE ONLY
    if cid:
        update_profile_and_intouch(
            int(cid),
            email=email,
            first_name=first_name,
            last_name=last_name,
            language=language,
            intouch_username=intouch_username,
            intouch_password=intouch_password,
        )

        pw = (password or "").strip()
        pw2 = (password2 or "").strip()
        if pw or pw2:
            if pw != pw2:
                return HTMLResponse("Passwords do not match.", status_code=400)
            if len(pw) < 8:
                return HTMLResponse("Password must be at least 8 characters.", status_code=400)
            set_consultant_password(int(cid), pw)

        return RedirectResponse("/app", status_code=302)

    # CASE B: Not logged in → CREATE NEW ACCOUNT
    if password != password2:
        return HTMLResponse("Passwords do not match.", status_code=400)

    if len(password) < 8:
        return HTMLResponse("Password must be at least 8 characters.", status_code=400)

    ok, msg, new_cid = create_consultant(email, password, language=language)
    if not ok:
        return HTMLResponse(msg, status_code=400)

    update_profile_and_intouch(
        int(new_cid),
        email=email,
        first_name=first_name,
        last_name=last_name,
        language=language,
        intouch_username=intouch_username,
        intouch_password=intouch_password,
    )

    request.session["consultant_id"] = int(new_cid)
    return RedirectResponse("/app", status_code=302)


@app.get("/onboard", response_class=HTMLResponse)
def onboard_get(request: Request):
    cid = request.session.get("consultant_id")
    c = get_consultant_full(int(cid)) if cid else None

    if c and is_profile_complete(c):
        return RedirectResponse("/app", status_code=302)

    lang = (c.get("language") if c else "en") or "en"
    if lang not in ("en", "es"):
        lang = "en"

    replaces = {
        "{{FIRST_NAME}}": (c.get("first_name") or "") if c else "",
        "{{LAST_NAME}}": (c.get("last_name") or "") if c else "",
        "{{EMAIL}}": (c.get("email") or "") if c else "",
        "{{INTOUCH_USERNAME}}": (c.get("intouch_username") or "") if c else "",
        "{{EN_SELECTED}}": "selected" if lang == "en" else "",
        "{{ES_SELECTED}}": "selected" if lang == "es" else "",
        "{{ERROR_BLOCK}}": "",
    }
    return render_page("onboard.html", replaces=replaces)


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

    index_path = WEB_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


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

    replaces = {
        "{{EMAIL}}": (c.get("email") or ""),
        "{{INTOUCH_USERNAME}}": (c.get("intouch_username") or ""),
        "{{LANG_VALUE}}": lang,
        "{{EN_ACTIVE}}": "active" if lang == "en" else "",
        "{{ES_ACTIVE}}": "active" if lang == "es" else "",
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
    try:
        _ = require_admin(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

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

        # Postgres often gives datetime directly
        if isinstance(val, datetime):
            dt = val
            # If naive, assume UTC (best-effort)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(CT)

        # Otherwise try parsing string
        s = str(val).strip()
        if not s:
            return None

        try:
            # normalize "Z" to "+00:00"
            s2 = s.replace("Z", "+00:00")

            # sqlite style "YYYY-MM-DD HH:MM:SS" -> iso-like
            if " " in s2 and "T" not in s2 and "+" not in s2:
                # treat as UTC
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
        # Example: 2026-02-17 7:10:03 PM CT
        return dt.strftime("%Y-%m-%d %-I:%M:%S %p CT")

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

    # 4) Recent DONE jobs (last 30)  ✅ NEW
    cur.execute(
        """
        SELECT id, consultant_id, type, status_msg, finished_at
        FROM jobs
        WHERE status='done'
        ORDER BY id DESC
        LIMIT 30
        """
    )
    done = cur.fetchall()

    # 5) Recent FAILED jobs (last 30)
    cur.execute(
        """
        SELECT id, consultant_id, type, error, finished_at
        FROM jobs
        WHERE status='failed'
        ORDER BY id DESC
        LIMIT 30
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
      {''.join([f"<tr><td>{r['id']}</td><td>{r['consultant_id']}</td><td>{r['type']}</td><td>{r['attempts']}</td><td>{r['claimed_by']}</td><td>{_fmt_ct(r['started_at'])}</td></tr>" for r in running_rows]) or "<tr><td colspan='6' class='muted'>No running jobs.</td></tr>"}
    </table>

    <!-- ✅ Completed above Failed -->
    <h2 style="margin:16px 0 6px;font-size:16px">Completed (last 30)</h2>
    <table>
      <tr>
        <th>id</th><th>consultant</th><th>type</th><th>message</th><th>finished (CT)</th>
      </tr>
      {''.join([f"<tr><td>{r['id']}</td><td>{r['consultant_id']}</td><td>{r['type']}</td><td>{(r['status_msg'] or '')}</td><td>{_fmt_ct(r['finished_at'])}</td></tr>" for r in done_rows]) or "<tr><td colspan='5' class='muted'>No completed jobs.</td></tr>"}
    </table>

    <h2 style="margin:16px 0 6px;font-size:16px">Recent failed (last 30)</h2>
    <table>
      <tr>
        <th>id</th><th>consultant</th><th>type</th><th>error</th><th>finished (CT)</th>
      </tr>
      {''.join([f"<tr><td>{r['id']}</td><td>{r['consultant_id']}</td><td>{r['type']}</td><td><code>{(r['error'] or '')[:300]}</code></td><td>{_fmt_ct(r['finished_at'])}</td></tr>" for r in failed_rows]) or "<tr><td colspan='5' class='muted'>No failed jobs.</td></tr>"}
    </table>

    <h2 style="margin:16px 0 6px;font-size:16px">Consultant locks</h2>
    <table>
      <tr>
        <th>consultant</th><th>locked_by</th><th>locked_at (CT)</th>
      </tr>
      {''.join([f"<tr><td>{r['consultant_id']}</td><td>{r['locked_by']}</td><td>{_fmt_ct(r['locked_at'])}</td></tr>" for r in lock_rows]) or "<tr><td colspan='3' class='muted'>No locks.</td></tr>"}
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
