import os
import re
#import sqlite3
from pathlib import Path
import time
import secrets
import hashlib
import requests
from urllib.parse import urlencode
from db import connect

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

load_dotenv()

from auth_core import authenticate, get_consultant, update_settings, set_consultant_password
from mk_chat_core import MKChatEngine, save_session_state

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mk.db"
WEB_DIR = BASE_DIR / "web"
PAGES_DIR = BASE_DIR / "pages"

app = FastAPI()

# -------------------------
# ENV
# -------------------------
SESSION_SECRET = os.environ.get("MK_SESSION_SECRET", "").strip()
if not SESSION_SECRET:
    raise RuntimeError("MK_SESSION_SECRET is not set. Export MK_SESSION_SECRET before starting the server.")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()  # e.g. "MyPinkAssistant <no-reply@mail.mypinkassistant.com>"
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").strip()  # e.g. "http://127.0.0.1:8000" or "https://mypinkassistant.com"

# 30 days "remember me"
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 24 * 30)

# Public static assets ONLY
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


# -------------------------
# DB helpers
# -------------------------
def _conn():
#    return sqlite3.connect(DB_PATH)
    return connect()

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _find_consultant_by_email(email: str):
    email = (email or "").strip().lower()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM consultants WHERE email=?", (email,))
    row = cur.fetchone()
    conn.close()
    return int(row[0]) if row else None


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


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    cid = request.session.get("consultant_id")
    if cid:
        # if onboard not complete, send to onboard; else app
        if not is_onboard_complete(int(cid)):
            return RedirectResponse("/onboard", status_code=302)
        return RedirectResponse("/app", status_code=302)

    return render_page("login.html")

@app.get("/splash.html", response_class=HTMLResponse)
def splash(request: Request):
    return render_page("splash.html")

@app.post("/login")
def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    cid = authenticate(email, password)
    if not cid:
        return HTMLResponse("Login failed. <a href='/login'>Try again</a>.", status_code=401)

    request.session["consultant_id"] = cid
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
    return HTMLResponse("""
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
""")


@app.post("/forgot", response_class=HTMLResponse)
def forgot_post(email: str = Form(...)):
    # Always show the same success screen (don’t reveal whether an email exists)
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
            # Table has: consultant_id, token_hash, expires_at, used_at, created_at
            cur.execute("""
                INSERT INTO password_resets (consultant_id, token_hash, expires_at)
                VALUES (?, ?, ?)
            """, (cid, token_hash, expires_str))
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

    return HTMLResponse("""
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
""")


# -------------------------
# Reset password
# -------------------------
@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_get(token: str = ""):
    token = (token or "").strip()
    if not token:
        return RedirectResponse("/login", status_code=302)

    return HTMLResponse(f"""
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
""")


@app.post("/reset-password", response_class=HTMLResponse)
def reset_password_post(request: Request, token: str = Form(...), password: str = Form(...), password2: str = Form(...)):

    token = (token or "").strip()
    if not token:
        return HTMLResponse("Invalid reset token. <a href='/forgot'>Try again</a>.", status_code=400)

    if (password or "") != (password2 or ""):
        return HTMLResponse("Passwords did not match. <a href='javascript:history.back()'>Go back</a>.", status_code=400)

    if len(password) < 8:
        return HTMLResponse("Password must be at least 8 characters. <a href='javascript:history.back()'>Go back</a>.", status_code=400)

    th = _hash_token(token)
    now = int(time.time())

    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT id, consultant_id, expires_at, used_at
      FROM password_resets
      WHERE token_hash=?
      ORDER BY id DESC
      LIMIT 1
    """, (th,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return HTMLResponse("That reset link is invalid. <a href='/forgot'>Try again</a>.", status_code=400)

    reset_id, cid, expires_at, used_at = row

    # expires_at stored as TEXT; we store epoch seconds as a string
    try:
        expires_i = int(str(expires_at))
    except Exception:
        expires_i = 0

    if used_at is not None:
        conn.close()
        return HTMLResponse("That reset link has already been used. <a href='/forgot'>Request a new one</a>.", status_code=400)

    if now > expires_i:
        conn.close()
        return HTMLResponse("That reset link has expired. <a href='/forgot'>Request a new one</a>.", status_code=400)

    # Mark used + update password
    cur.execute("UPDATE password_resets SET used_at=datetime('now') WHERE id=?", (reset_id,))
    conn.commit()
    conn.close()

    set_consultant_password(int(cid), password)
    # Clear any existing login session
    request.session.clear()

    # Redirect to login page
    return RedirectResponse("/login", status_code=302)

##


# -------------------------
# Protected app page
# -------------------------
@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return RedirectResponse("/login", status_code=302)

    # 🔽 ADD THIS BLOCK
    from auth_core import get_consultant_full  # if not already imported

    c = get_consultant_full(cid)
    if not c or not is_profile_complete(c):
        return RedirectResponse("/onboard", status_code=302)
    # 🔼 END BLOCK

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

@app.get("/onboard", response_class=HTMLResponse)
def onboard_get(request: Request):
    return render_page("onboard.html")

    c = get_consultant_full(cid)  # (see note below)
    if c and is_profile_complete(c):
        return RedirectResponse("/app", status_code=302)

    lang = (c.get("language") if c else "en") or "en"
    lang = lang if lang in ("en", "es") else "en"

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


from auth_core import create_consultant, update_settings

@app.post("/onboard")
def onboard_post(
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    intouch_username: str = Form(...),
    intouch_password: str = Form(...),
):
    if password != password2:
        return HTMLResponse("Passwords do not match.", status_code=400)

    # Create consultant account
    ok, msg, cid = create_consultant(email, password)
    if not ok:
        return HTMLResponse(msg, status_code=400)

    # Save settings (including encrypted InTouch password)
    update_settings(
        cid,
        language="en",
        intouch_username=intouch_username,
        intouch_password=intouch_password,
    )

    # Log them in automatically
    from fastapi import Request
    # You'll need request injected if not already
    # request.session["consultant_id"] = cid

    return RedirectResponse("/app", status_code=302)

@app.get("/jobs")
def jobs(request: Request):
    try:
        cid = require_login(request)
    except PermissionError:
        return JSONResponse({"jobs": []}, status_code=401)

    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, type, status, error, status_msg
        FROM jobs
        WHERE consultant_id = ?
        ORDER BY id DESC
        LIMIT 25
        """,
        (cid,),
    )
    rows = cur.fetchall()
    conn.close()

    out = [
        {"id": r[0], "type": r[1], "status": r[2], "error": r[3] or "", "status_msg": r[4] or ""}
        for r in rows
    ]
    return {"jobs": out}


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
