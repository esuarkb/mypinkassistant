import os
#import sqlite3
import hashlib
import secrets
from pathlib import Path
from typing import Optional, Tuple

from cryptography.fernet import Fernet
from db import connect

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "mk.db"


def _get_conn():
    return connect()
#    return sqlite3.connect(DB_PATH)


# -------------------------
# Password hashing (PBKDF2)
# -------------------------
def pbkdf2_hash(password: str, iterations: int = 310_000) -> str:
    """
    Returns a string like:
      pbkdf2_sha256$iterations$salt_hex$hash_hex
    """
    password = password or ""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def pbkdf2_verify(password: str, stored: str) -> bool:
    # stored: pbkdf2_sha256$iterations$salt_hex$hash_hex
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters_i = int(iters)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            (password or "").encode("utf-8"),
            bytes.fromhex(salt_hex),
            iters_i,
        )
        return dk.hex() == hash_hex
    except Exception:
        return False

import secrets

def pbkdf2_hash(password: str, iterations: int = 260_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"

def set_consultant_password(cid: int, new_password: str) -> None:
    ph = pbkdf2_hash(new_password)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE consultants SET password_hash=? WHERE id=?", (ph, cid))
    conn.commit()
    conn.close()

# -------------------------
# Intouch encryption (Fernet)
# -------------------------
def get_fernet() -> Fernet:
    key = os.environ.get("MK_ENC_KEY", "").strip()
    if not key:
        raise RuntimeError("MK_ENC_KEY is not set. Export MK_ENC_KEY before starting the server.")
    return Fernet(key.encode("utf-8"))


def encrypt_intouch_password(plain: str) -> str:
    if not plain:
        return ""
    f = get_fernet()
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_intouch_password(enc: str) -> str:
    if not enc:
        return ""
    f = get_fernet()
    return f.decrypt(enc.encode("utf-8")).decode("utf-8")


# -------------------------
# Auth + Consultant helpers
# -------------------------
def authenticate(email: str, password: str) -> Optional[int]:
    email = (email or "").strip().lower()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM consultants WHERE email=?", (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    cid, ph = row
    if pbkdf2_verify(password or "", ph):
        return int(cid)
    return None


def create_consultant(email: str, password: str, language: str = "en") -> Tuple[bool, str, Optional[int]]:
    """
    Creates a new consultant.
    Returns (ok, message, consultant_id)
    """
    email = (email or "").strip().lower()
    password = password or ""

    if "@" not in email or "." not in email:
        return (False, "Please enter a valid email address.", None)
    if len(password) < 8:
        return (False, "Password must be at least 8 characters.", None)

    language = (language or "en").strip().lower()
    if language not in ("en", "es"):
        language = "en"

    conn = _get_conn()
    cur = conn.cursor()

    # Make sure email is unique
    cur.execute("SELECT id FROM consultants WHERE email=?", (email,))
    if cur.fetchone():
        conn.close()
        return (False, "An account with that email already exists. Try logging in.", None)

    ph = pbkdf2_hash(password)

    cur.execute(
        """
        INSERT INTO consultants (email, password_hash, language, intouch_username, intouch_password_enc)
        VALUES (?, ?, ?, '', '')
        """,
        (email, ph, language),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return (True, "Account created.", int(cid))


def get_consultant(cid: int) -> Optional[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, email, language, intouch_username
        FROM consultants WHERE id=?
        """,
        (cid,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "language": row[2],
        "intouch_username": row[3] or "",
    }


def get_consultant_intouch_creds(cid: int) -> Tuple[str, str]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT intouch_username, intouch_password_enc
        FROM consultants WHERE id=?
        """,
        (cid,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return ("", "")
    u = row[0] or ""
    p_enc = row[1] or ""
    p = decrypt_intouch_password(p_enc) if p_enc else ""
    return (u, p)


def update_settings(cid: int, language: str, intouch_username: str, intouch_password: str | None) -> None:
    language = (language or "en").strip().lower()
    if language not in ("en", "es"):
        language = "en"

    iu = (intouch_username or "").strip()

    conn = _get_conn()
    cur = conn.cursor()

    if intouch_password is not None and intouch_password.strip() != "":
        enc = encrypt_intouch_password(intouch_password.strip())
        cur.execute(
            """
            UPDATE consultants
            SET language=?, intouch_username=?, intouch_password_enc=?
            WHERE id=?
            """,
            (language, iu, enc, cid),
        )
    else:
        # If password omitted, keep existing saved password
        cur.execute(
            """
            UPDATE consultants
            SET language=?, intouch_username=?
            WHERE id=?
            """,
            (language, iu, cid),
        )

    conn.commit()
    conn.close()
    
# --- add to auth_core.py (at bottom) ---

import secrets
import datetime


def pbkdf2_hash(password: str, iterations: int = 210_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def create_consultant(email: str, password: str) -> int:
    email = (email or "").strip().lower()
    if not email or not password:
        raise ValueError("Email and password are required.")

    ph = pbkdf2_hash(password)

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO consultants (email, password_hash, language, intouch_username, intouch_password_enc) VALUES (?, ?, 'en', '', '')",
            (email, ph),
        )
        cid = cur.lastrowid
        conn.commit()
        return int(cid)
    finally:
        conn.close()


def set_consultant_password(cid: int, new_password: str) -> None:
    ph = pbkdf2_hash(new_password)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE consultants SET password_hash=? WHERE id=?", (ph, cid))
    conn.commit()
    conn.close()


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def create_password_reset(email: str, ttl_minutes: int = 30) -> str | None:
    """
    Returns a raw token if email exists; otherwise None.
    We store only a hash in DB.
    """
    email = (email or "").strip().lower()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM consultants WHERE email=?", (email,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    cid = int(row[0])

    token = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(token)

    expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        "INSERT INTO password_resets (consultant_id, token_hash, expires_at) VALUES (?, ?, ?)",
        (cid, token_hash, expires),
    )
    conn.commit()
    conn.close()
    return token


def consume_password_reset(token: str) -> int | None:
    """
    If token is valid + not expired + not used, mark used and return consultant_id.
    Otherwise return None.
    """
    if not token:
        return None

    token_hash = _sha256_hex(token)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, consultant_id, expires_at, used_at
        FROM password_resets
        WHERE token_hash=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (token_hash,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    reset_id, cid, expires_at, used_at = row
    if used_at:
        conn.close()
        return None

    # Compare expiry as text timestamps (SQLite-friendly)
    cur.execute("SELECT datetime('now')")
    now_row = cur.fetchone()
    now_str = now_row[0] if now_row else ""

    if expires_at <= now_str:
        conn.close()
        return None

    cur.execute("UPDATE password_resets SET used_at=datetime('now') WHERE id=?", (reset_id,))
    conn.commit()
    conn.close()
    return int(cid)

