## complete auth_core replace 9:09 am sat

# auth_core.py
from __future__ import annotations

import os
import hashlib
import secrets
from typing import Optional, Tuple

from cryptography.fernet import Fernet

from db import connect, is_postgres

# Placeholder style differs:
# - SQLite: ?
# - Postgres (psycopg): %s
PH = "%s" if is_postgres() else "?"


# -------------------------
# DB helper
# -------------------------
def _get_conn():
    return connect()


def _row_get(row, key: str, idx: int):
    """
    Works whether row is a tuple/list/sqlite3.Row (sqlite) or dict-like (psycopg dict_row).
    """
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    # sqlite3.Row supports index access
    return row[idx]


# -------------------------
# Password hashing (PBKDF2)
# -------------------------
def pbkdf2_hash(password: str, iterations: int = 310_000) -> str:
    """
    Returns: pbkdf2_sha256$iterations$salt_hex$hash_hex
    """
    password = password or ""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def pbkdf2_verify(password: str, stored: str) -> bool:
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


def set_consultant_password(cid: int, new_password: str) -> None:
    ph = pbkdf2_hash(new_password)
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(f"UPDATE consultants SET password_hash={PH} WHERE id={PH}", (ph, cid))
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


# -------------------------
# InTouch encryption (Fernet)
# -------------------------
def get_fernet() -> Fernet:
    key = os.environ.get("MK_ENC_KEY", "").strip()
    if not key:
        raise RuntimeError("MK_ENC_KEY is not set. Set MK_ENC_KEY before starting the server.")
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
    try:
        cur.execute(
            f"SELECT id, password_hash FROM consultants WHERE email={PH}",
            (email,),
        )
        row = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    if not row:
        return None

    cid = _row_get(row, "id", 0)
    ph = _row_get(row, "password_hash", 1)

    if ph and pbkdf2_verify(password or "", ph):
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
    try:
        # Unique email
        cur.execute(f"SELECT id FROM consultants WHERE email={PH}", (email,))
        if cur.fetchone():
            return (False, "An account with that email already exists. Try logging in.", None)

        pw_hash = pbkdf2_hash(password)

        if is_postgres():
            # Postgres: RETURNING id
            cur.execute(
                f"""
                INSERT INTO consultants (email, password_hash, language, intouch_username, intouch_password_enc)
                VALUES ({PH}, {PH}, {PH}, '', '')
                RETURNING id
                """,
                (email, pw_hash, language),
            )
            row = cur.fetchone()
            new_id = _row_get(row, "id", 0)
        else:
            # SQLite: lastrowid
            cur.execute(
                f"""
                INSERT INTO consultants (email, password_hash, language, intouch_username, intouch_password_enc)
                VALUES ({PH}, {PH}, {PH}, '', '')
                """,
                (email, pw_hash, language),
            )
            new_id = cur.lastrowid

        conn.commit()
        return (True, "Account created.", int(new_id))
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def get_consultant(cid: int) -> Optional[dict]:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT id, email, language, intouch_username
            FROM consultants
            WHERE id={PH}
            """,
            (cid,),
        )
        row = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    if not row:
        return None

    return {
        "id": _row_get(row, "id", 0),
        "email": _row_get(row, "email", 1),
        "language": _row_get(row, "language", 2),
        "intouch_username": _row_get(row, "intouch_username", 3) or "",
    }


def get_consultant_full(cid: int) -> Optional[dict]:
    """
    Full consultant row needed for onboard/profile checks + billing gate.
    IMPORTANT: uses _row_get so it works for both sqlite + postgres dict_row.
    """
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT
                id,
                email,
                first_name,
                last_name,
                language,
                intouch_username,
                intouch_password_enc,

                stripe_customer_id,
                stripe_subscription_id,
                billing_status,
                trial_end,
                current_period_end,
                cancel_at_period_end,
                onboarding_complete,
                last_billing_event_at
            FROM consultants
            WHERE id={PH}
            """,
            (cid,),
        )
        row = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    if not row:
        return None

    return {
        "id": _row_get(row, "id", 0),
        "email": _row_get(row, "email", 1),
        "first_name": (_row_get(row, "first_name", 2) or ""),
        "last_name": (_row_get(row, "last_name", 3) or ""),
        "language": (_row_get(row, "language", 4) or "en"),
        "intouch_username": (_row_get(row, "intouch_username", 5) or ""),
        "intouch_password_enc": (_row_get(row, "intouch_password_enc", 6) or ""),

        # billing fields
        "stripe_customer_id": (_row_get(row, "stripe_customer_id", 7) or ""),
        "stripe_subscription_id": (_row_get(row, "stripe_subscription_id", 8) or ""),
        "billing_status": (_row_get(row, "billing_status", 9) or ""),
        "trial_end": (_row_get(row, "trial_end", 10) or ""),
        "current_period_end": (_row_get(row, "current_period_end", 11) or ""),
        "cancel_at_period_end": int(_row_get(row, "cancel_at_period_end", 12) or 0),
        "onboarding_complete": int(_row_get(row, "onboarding_complete", 13) or 0),
        "last_billing_event_at": (_row_get(row, "last_billing_event_at", 14) or ""),
    }


def update_profile_and_intouch(
    cid: int,
    email: str,
    first_name: str,
    last_name: str,
    language: str,
    intouch_username: str,
    intouch_password: str,
) -> None:
    email = (email or "").strip().lower()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    language = (language or "en").strip().lower()
    if language not in ("en", "es"):
        language = "en"

    iu = (intouch_username or "").strip()
    pw = (intouch_password or "").strip()
    enc = encrypt_intouch_password(pw) if pw else ""

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE consultants
            SET email={PH}, first_name={PH}, last_name={PH}, language={PH},
                intouch_username={PH}, intouch_password_enc={PH}
            WHERE id={PH}
            """,
            (email, first_name, last_name, language, iu, enc, cid),
        )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def get_consultant_intouch_creds(cid: int) -> Tuple[str, str]:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT intouch_username, intouch_password_enc
            FROM consultants
            WHERE id={PH}
            """,
            (cid,),
        )
        row = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    if not row:
        return ("", "")

    u = _row_get(row, "intouch_username", 0) or ""
    p_enc = _row_get(row, "intouch_password_enc", 1) or ""
    p = decrypt_intouch_password(p_enc) if p_enc else ""
    return (u, p)


def update_settings(cid: int, language: str, intouch_username: str, intouch_password: str | None) -> None:
    language = (language or "en").strip().lower()
    if language not in ("en", "es"):
        language = "en"

    iu = (intouch_username or "").strip()

    conn = _get_conn()
    cur = conn.cursor()
    try:
        if intouch_password is not None and intouch_password.strip() != "":
            enc = encrypt_intouch_password(intouch_password.strip())
            cur.execute(
                f"""
                UPDATE consultants
                SET language={PH}, intouch_username={PH}, intouch_password_enc={PH},
                    consecutive_login_failures=0, last_login_failure_at=NULL
                WHERE id={PH}
                """,
                (language, iu, enc, cid),
            )
        else:
            # If password omitted, keep existing saved password
            cur.execute(
                f"""
                UPDATE consultants
                SET language={PH}, intouch_username={PH}
                WHERE id={PH}
                """,
                (language, iu, cid),
            )

        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()
