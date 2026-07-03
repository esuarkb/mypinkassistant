"""Field normalizers and parsers: phone, state, city, birthday, address,
yes/no answers. Pure text-in/text-out — no DB, no OpenAI.
"""
import calendar
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")

def yes(s: str) -> bool:
    return (s or "").strip().lower() in (
        "y", "yes", "yeah", "yep", "ok", "okay", "confirm", "correct", "right",
        "si", "sí",  # optional Spanish
    )

def no(s: str) -> bool:
    return (s or "").strip().lower() in (
        "n", "no", "nope", "nah", "wrong", "incorrect",
    )

def format_phone_display(phone: str) -> str:
    digits = normalize_phone(phone)
    if not digits:
        return ""
    if len(digits) >= 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) >= 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    if len(digits) == 7:
        return f"{digits[0:3]}-{digits[3:7]}"
    return digits

STATE_MAP = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "Washington, D.C.",
}

def normalize_state(state: str) -> str:
    s = (state or "").strip()
    if not s:
        return ""
    # Normalize DC variants
    if s.upper() in ("DC", "D.C.", "WASHINGTON DC", "WASHINGTON D.C.", "DISTRICT OF COLUMBIA"):
        return "Washington, D.C."
    if len(s) == 2:
        return STATE_MAP.get(s.upper(), s)
    return s

# NUMBER_WORDS / _parse_small_number moved to intent_router.py (2026-07-02)

STREET_SUFFIXES = (
    "st", "street", "rd", "road", "ave", "avenue", "blvd", "boulevard",
    "dr", "drive", "ln", "lane", "ct", "court", "cir", "circle",
    "pkwy", "parkway", "hwy", "highway", "pl", "place", "way"
)

def _append_unit_suffix_if_present(street: str, extra: str) -> tuple:
    unit_words = ("apt", "apartment", "unit", "lot", "suite", "ste", "#", "trlr", "trailer", "bldg", "building", "spc", "space")
    extra = (extra or "").strip()

    if extra:
        if not any(word in extra.lower() for word in unit_words):
            return street, ""

        # Stop before anything that looks like a date, like 10-14 or 10/14
        parts = extra.split()
        clean_parts = []
        for p in parts:
            if re.match(r"\d{1,2}[-/]\d{1,2}$", p):
                break
            clean_parts.append(p)

        extra_clean = " ".join(clean_parts).strip()
        return street, extra_clean if extra_clean else ""

    # No extra — check if the street string itself contains a unit keyword
    # e.g. "555 5th st apt 5" -> ("555 5th st", "apt 5")
    street_lower = street.lower()
    for word in unit_words:
        m = re.search(r'\b' + re.escape(word) + r'\b', street_lower)
        if m:
            base = street[:m.start()].strip()
            unit = street[m.start():].strip()
            if base:
                return base, unit

    return street, ""

def _parse_address_line_raw(s: str) -> Optional[Dict[str, str]]:
    """
    Best-effort parse of an address line into:
      Street, City, State, Postal Code

    Supports:
      - "444 4th St Arab, AL 35976"
      - "444 4th St, Arab, AL 35976"
      - "333 3rd st" (street-only)
    """
    raw = (s or "").strip()
    if not raw:
        return None

    # Normalize whitespace
    txt = re.sub(r"\s+", " ", raw).strip()

    # Special case: "31 W East st madison, WI 35976"
    # Split street at a real street suffix, then treat the rest as city/state/zip.
    m = re.match(
        r"^(?P<street>.+?\b(?:st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|ct|court|cir|circle|pkwy|parkway|hwy|highway|pl|place|way)\b)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s*,\s*(?P<state>[A-Za-z]{2,}(?:\s+[A-Za-z]+)?)\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt,
        re.IGNORECASE,
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # Special case (no comma): "232 Queens St Sun Prairie WI 53590"
    # Same suffix-split logic as above but without requiring a comma before state.
    m = re.match(
        r"^(?P<street>.+?\b(?:st|street|rd|road|ave|avenue|blvd|boulevard|dr|drive|ln|lane|ct|court|cir|circle|pkwy|parkway|hwy|highway|pl|place|way)\b)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s+(?P<state>[A-Za-z]{2,}(?:\s+[A-Za-z]+)?)\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt,
        re.IGNORECASE,
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # Pull ZIP first (required for full parse).
    # Skip a 5-digit match at position 0 — that's a house number, not a zip.
    mzip = re.search(r"\b(\d{5})(?:-\d{4})?\b", txt)
    zip5 = mzip.group(1) if (mzip and mzip.start() > 0) else ""

    # ---------- Pattern A: "street city, ST ZIP"
    # Example: "444 4th St Arab, AL 35976"
    m = re.match(
        r"^(?P<street>.+?)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s*,\s*(?P<state>[A-Za-z]{2,}(?:\s+[A-Za-z]+)?)\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt
    )
    if m:
        street = m.group("street").strip().rstrip(",").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern B: "street, city, ST ZIP"
    # Example: "444 4th St, Arab, AL 35976"
    m = re.match(
        r"^(?P<street>.+?)\s*,\s*(?P<city>.+?)\s*,\s*(?P<state>[A-Za-z]{2,}(?:\s+[A-Za-z]+)?)\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern D: "street city ST ZIP" (no commas)
    # Example: "333 3rd st arab al 35976"
    m = re.match(
        r"^(?P<street>.+?)\s+(?P<city>[A-Za-z][A-Za-z .'\-]+)\s+(?P<state>[A-Za-z]{2,}(?:\s+[A-Za-z]+)?)\s+(?P<zip>\d{5})(?:-\d{4})?(?P<extra>\s+.*)?$",
        txt
    )
    if m:
        street = m.group("street").strip()
        extra = (m.group("extra") or "").strip()
        street, street2 = _append_unit_suffix_if_present(street, extra)

        return {
            "Street": street,
            "Street2": street2,
            "City": m.group("city").strip(),
            "State": m.group("state").strip(),
            "Postal Code": m.group("zip").strip(),
        }

    # ---------- Pattern C: street-only
    # Only accept street-only if it looks like a street line (has a number + suffix)
    low = txt.lower()
    has_number = bool(re.search(r"\d", low))
    has_suffix = any(re.search(rf"\b{re.escape(suf)}\b", low) for suf in STREET_SUFFIXES)

    if has_number and has_suffix and not zip5:
        return {"Street": txt}

    # If it has a zip but didn't match full patterns, don't guess (avoid bad splits)
    return None


def parse_address_line(s: str) -> Optional[Dict[str, str]]:
    result = _parse_address_line_raw(s)
    if result:
        if result.get("Street"):
            result["Street"] = _normalize_street(result["Street"])
        if result.get("Street2"):
            result["Street2"] = _normalize_street(result["Street2"])
    return result


def _normalize_street(s: str) -> str:
    titled = s.title()
    # Keep ordinal suffixes lowercase: "5Th" → "5th", "3Rd" → "3rd"
    return re.sub(r'\b(\d+)(St|Nd|Rd|Th)\b', lambda m: m.group(1) + m.group(2).lower(), titled)


def normalize_city(city: str) -> str:
    s = (city or "").strip()
    if not s:
        return ""
    # Fix "st X" → "St. X" (e.g. "st paul" → "St. Paul")
    # Also handle "st." prefix and bleed cases like "st st paul" or "st. st paul"
    s = re.sub(r"^st\.?\s+st\.?\s*", "St. ", s, flags=re.IGNORECASE)
    s = re.sub(r"^st\.?\s+", "St. ", s, flags=re.IGNORECASE)
    # Title case the result
    return s.title()


def normalize_birthday(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            y, mo, d = map(int, s.split("-"))
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return ""

    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", s)
    if m:
        mo = int(m.group(1))
        d = int(m.group(2))
        y_raw = m.group(3)
        if y_raw is None:
            y = 2000
        else:
            y_i = int(y_raw)
            if len(y_raw) == 2:
                y = 2000 + y_i if y_i <= 29 else 1900 + y_i
            else:
                y = y_i
        try:
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return ""

    s2 = re.sub(r"[.,]", " ", s)
    s2 = re.sub(r"\s+", " ", s2).strip()

    month_map = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    month_map.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})

    parts = s2.split(" ")

    def _try(month_token: str, day_token: str, year_token: str | None) -> str:
        mo = month_map.get(month_token.lower())
        if not mo:
            return ""
        try:
            d = int(day_token)
        except Exception:
            return ""
        if year_token is None or year_token == "":
            y = 2000
        else:
            try:
                y_i = int(year_token)
            except Exception:
                return ""
            if len(year_token) == 2:
                y = 2000 + y_i if y_i <= 29 else 1900 + y_i
            else:
                y = y_i
        try:
            datetime.date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except Exception:
            return ""

    if len(parts) >= 2 and parts[0].lower() in month_map:
        year = parts[2] if len(parts) >= 3 else None
        out = _try(parts[0], parts[1], year)
        if out:
            return out

    if len(parts) >= 2 and parts[1].lower() in month_map:
        year = parts[2] if len(parts) >= 3 else None
        out = _try(parts[1], parts[0], year)
        if out:
            return out

    return ""


def birthday_display(normalized: str) -> str:
    s = (normalized or "").strip()

    # Full date
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        y, mo, d = map(int, s.split("-"))
        month = calendar.month_name[mo]
        # Year 2000 is our default placeholder when no year was provided — don't show it
        if y == 2000:
            return f"{month} {d}"
        return f"{month} {d}, {y}"

    # Month/day only
    if re.fullmatch(r"\d{2}-\d{2}", s):
        mo, d = map(int, s.split("-"))
        month = calendar.month_name[mo]
        return f"{month} {d}"

    return ""
