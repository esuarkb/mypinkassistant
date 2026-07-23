"""Parsing consultant corrections to a pending customer confirm
("her email is x@y.com", new address lines, birthday fixes).
"""
import re
from typing import Dict, List, Tuple

from .normalize import (
    _normalize_street,
    normalize_birthday,
    normalize_city,
    normalize_phone,
    normalize_state,
    parse_address_line,
)


def looks_like_command(msg: str) -> bool:
    s = (msg or "").strip().lower()
    if not s:
        return False

    # direct command starts
    command_starts = (
        "show ", "lookup ", "info ", "information ",
        "what is", "what's", "whats",
        "top ", "leaderboard", "spent", "last ", "recent ", "history",
        "new customer", "add customer", "create customer", "create ",
        "new order", "order for", "add order",
        "delete ", "remove ",
    )

    if s.startswith(command_starts):
        return True

    # detect possessive info requests like: "Jane's info"
    if re.search(r"\b\w+'\s*s?\s*(info|email|phone|address|birthday)\b", s):
        return True

    # "add birthday X", "update phone X" etc. are field edits, not lookups
    if re.match(r'^(add|edit|update|change)\s+(birthday|birthdate|bday|phone|email|address|name|tag|referred)', s):
        return False

    # detect patterns like "Jane info"
    if re.search(r"\b\w+\s+(info|email|phone|address|birthday)\b", s):
        return True

    # detect "top X customers"
    if re.search(r"\btop\s*\d+\s*customers?\b", s):
        return True

    return False

def split_edit_parts(message: str) -> List[str]:
    """
    Splits a user edit message into chunks.
    IMPORTANT:
    - Do NOT split on commas (addresses)
    - Do NOT split on 'and' (addresses like 'Fish and Game Rd')
    """
    s = (message or "").strip()
    if not s:
        return []

    # Split only on semicolons OR newlines
    parts = re.split(r"\s*;\s*|\n+", s)

    return [p.strip() for p in parts if p.strip()]


def _looks_like_email(s: str) -> bool:
    return bool(re.search(r"[^\s]+@[^\s]+\.[^\s]+", s or ""))


def _extract_email(s: str) -> str:
    m = re.search(r"([^\s]+@[^\s]+\.[^\s]+)", s or "")
    return (m.group(1).strip() if m else "").strip()


def _extract_zip(s: str) -> str:
    m = re.search(r"\b(\d{5})\b", s or "")
    return (m.group(1) if m else "").strip()


def _extract_phone_candidate(s: str) -> str:
    # Require recognizable phone grouping — avoids treating street numbers
    # like "10208 NE 75th way" as a 7-digit phone after digit stripping.
    # 10/11-digit: (NNN) NNN-NNNN, NNN-NNN-NNNN, NNNNNNNNNN, +1NNN...
    m = re.search(
        r"(?:\+?1[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})",
        s,
    )
    if m:
        digits = normalize_phone(m.group(0))
        if len(digits) in (10, 11):
            return digits
    # 7-digit local: NNN-NNNN or NNNNNNN (digits only, word-boundary delimited)
    m = re.search(r"\b\d{3}[\s\-.]?\d{4}\b", s)
    if m:
        digits = normalize_phone(m.group(0))
        if len(digits) == 7:
            return digits
    return ""


def _looks_like_birthday(s: str) -> bool:
    s2 = (s or "").strip()
    if not s2:
        return False
    # MM/DD, M-D, MM/DD/YYYY, YYYY-MM-DD, "Oct 14"
    if re.search(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", s2):
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s2):
        return True
    # month name + day
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b", s2, re.IGNORECASE):
        return True
    return False


def _looks_like_new_customer_paste(txt: str) -> bool:
    """True when a mid-confirm input reads as a whole NEW customer pasted in — a
    leading name (First Last …) plus a phone or birthday somewhere — rather than
    a single-field correction. During a pending customer-confirm every non-yes/no
    line is treated as an edit; without this guard a consultant bulk-entering
    customers who pastes the NEXT person has that person's details written into
    the customer still on screen. That corrupted 2 InTouch records (jobs 9928/
    9938, weed-garden 2026-07-22 F1). A real address correction leads with a house
    number, so requiring a leading NAME keeps this off legitimate edits."""
    s = (txt or "").strip()
    toks = s.split()
    if len(toks) < 3 or not (toks[0].isalpha() and toks[1].isalpha()):
        return False
    return bool(_extract_phone_candidate(s)) or _looks_like_birthday(s)


def apply_customer_edits(customer: dict, message: str) -> Tuple[dict, List[str]]:
    """
    Applies 'add/edit' instructions to a pending customer dict.
    Returns: (updated_customer, notes[])
    """
    c = dict(customer or {})
    notes: List[str] = []

    parts = split_edit_parts(message)

    for raw in parts:
        txt = raw.strip()
        low = txt.lower()

        # strip leading verbs
        for prefix in ("edit ", "edit:", "add ", "add:", "update ", "update:"):
            if low.startswith(prefix):
                txt = txt[len(prefix):].strip()
                low = txt.lower()
                break

        if not txt:
            continue

        # --- Explicit field targets first ---
        # email:
        if low.startswith("email"):
            email = _extract_email(txt)
            if email:
                c["Email"] = email
                notes.append("Email updated")
            continue

        # phone:
        if low.startswith("phone") or low.startswith("cell") or low.startswith("mobile"):
            ph = _extract_phone_candidate(txt)
            if ph:
                c["Phone"] = ph
                notes.append("Phone updated")
            continue

        # birthday:
        if low.startswith("birthday") or low.startswith("birthdate") or low.startswith("bday") or low.startswith("dob"):
            b_raw = re.sub(r"^(birthday|birthdate|bday|dob)\s*(?:is|was)?\s*[:\-]?\s*", "", txt, flags=re.IGNORECASE).strip()
            b = normalize_birthday(b_raw)
            if b:
                c["Birthday"] = b
                notes.append("Birthday updated")
            continue

        # referred by:
        if low.startswith("referred by") or low.startswith("referral") or low.startswith("ref by"):
            ref = re.sub(r"^(referred\s+by|referral\s+from|referral|ref\s+by)\s*[:\-]?\s*", "", txt, flags=re.IGNORECASE).strip()
            if ref:
                c["Referred By"] = ref
                notes.append("Referred By updated")
            continue

        # tags:
        if low.startswith("tag"):
            raw = re.sub(r"^tags?\s*[:\-]?\s*", "", txt, flags=re.IGNORECASE).strip()
            tags = ", ".join(t.strip() for t in raw.split(",") if t.strip())
            if tags:
                c["Tags"] = tags
                notes.append("Tags updated")
            continue

        # address: (Spanish "Dirección:" too — ES customer pastes kept the
        # prefix in the street field; added 2026-07-11)
        if low.startswith("address") or low.startswith("dirección") or low.startswith("direccion"):
            addr = re.sub(r"^(?:address|direcci[oó]n)\s*(?:is|was|at|es)?\s*[:\-]?\s*", "", txt, flags=re.IGNORECASE).strip()
            if addr:
                # ✅ Try smart parse first
                parsed = parse_address_line(addr)
                if parsed:
                    c.update(parsed)
                    notes.append("Address updated")
                    continue

                # Fallback: your existing comma split
                if "," in addr:
                    chunks = [x.strip().strip(",") for x in addr.split(",") if x.strip()]
                    if len(chunks) >= 2:
                        c["Street"] = _normalize_street(chunks[0])
                        c["City"] = chunks[1]
                        if len(chunks) >= 3:
                            stzip = chunks[2]
                            z = _extract_zip(stzip)
                            if z:
                                c["Postal Code"] = z
                            st_only = re.sub(r"\b\d{5}\b", "", stzip).strip()
                            if st_only:
                                c["State"] = st_only
                        notes.append("Address updated")
                        continue

                # Final fallback: at least save it
                c["Street"] = _normalize_street(addr)
                notes.append("Address updated (street)")
            continue

        # --- Guess by format ---
        # Data-integrity guard (weed-garden 2026-07-22 F1): if this line reads as
        # a whole NEW customer pasted mid-confirm (leading name + phone/birthday),
        # do NOT let the format guesses below nibble fields off it into the
        # pending customer. Leave the customer untouched and note it — safer than
        # corrupting a record that then lands in InTouch.
        if _looks_like_new_customer_paste(txt):
            notes.append(f"Couldn't apply: “{raw}”")
            continue

        # Email guess
        if _looks_like_email(txt):
            c["Email"] = _extract_email(txt)
            notes.append("Email updated")
            continue

        # Birthday guess
        if _looks_like_birthday(txt):
            b = normalize_birthday(txt)
            if b:
                c["Birthday"] = b
                notes.append("Birthday updated")
                continue

        # ✅ Address guess (must be BEFORE zip guess)
        parsed = parse_address_line(txt)
        if parsed:
            c.update(parsed)
            notes.append("Address updated")
            continue

        # Phone guess
        ph = _extract_phone_candidate(txt)
        if ph:
            c["Phone"] = ph
            notes.append("Phone updated")
            continue



        # Zip guess
        z = _extract_zip(txt)
        if z:
            c["Postal Code"] = z
            notes.append("Postal code updated")
            continue

        # Fallback: if they typed something else, ignore but keep a note
        notes.append(f"Couldn't apply: “{raw}”")

    # Clean punctuation that causes "Street," to get saved to JSON
    for k in ("Street", "City", "State"):
        if k in c and isinstance(c[k], str):
            c[k] = c[k].strip().rstrip(",")

    # Re-normalize (important!)
    c["Phone"] = normalize_phone(c.get("Phone", ""))
    c["Birthday"] = normalize_birthday(c.get("Birthday", ""))
    c["State"] = normalize_state(c.get("State", ""))
    c["City"] = normalize_city(c.get("City", ""))

    return c, notes
