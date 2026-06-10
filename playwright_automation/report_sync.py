# playwright_automation/report_sync.py
#
# Syncs team/unit member data from InTouch for any consultant with a team.
# Populates: unit_members, unit_great_start, unit_star_tracking,
#            unit_rise_radiate, unit_registrations
#
# Call run_report_sync(page, cur, consultant_id) after login_intouch() has run.

import json
import urllib.parse
from datetime import date, datetime
from playwright.sync_api import Page

import requests

_CONSULTANT_LIST_URL = "https://mk.marykayintouch.com/s/consultant-list"
_AURA_FRAGMENT = "sfsites/aura"
_FOREPORTS_BASE = "https://applications.marykayintouch.com/FOReports/api"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _current_production_month() -> str:
    """First day of current month: YYYY-MM-01."""
    today = date.today()
    return today.replace(day=1).isoformat()


def _current_quarter_date() -> str:
    """A date within the current Star Consultant contest quarter."""
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Aura response parser — recursively finds the consultants list
# ---------------------------------------------------------------------------

def _find_consultants(obj, depth: int = 0) -> list | None:
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if "consultants" in obj:
            c = obj["consultants"]
            if isinstance(c, list) and len(c) > 0:
                return c
        for v in obj.values():
            result = _find_consultants(v, depth + 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_consultants(item, depth + 1)
            if result is not None:
                return result
    return None


# ---------------------------------------------------------------------------
# Fetch consultant list via Playwright response interception
# ---------------------------------------------------------------------------

def fetch_unit_members(page: Page) -> list[dict]:
    """
    Navigate to the consultant-list page and capture the Aura batch response
    that contains the unit member data. Returns a list of raw consultant dicts.
    """
    captured: list[dict] = []

    def _on_response(response):
        if _AURA_FRAGMENT not in response.url:
            return
        try:
            body = response.json()
            consultants = _find_consultants(body)
            if consultants:
                print(f"[ReportSync] Found {len(consultants)} unit members in Aura response")
                captured.extend(consultants)
        except Exception as e:
            print(f"[ReportSync] Aura parse error: {e}")

    page.on("response", _on_response)
    page.goto(_CONSULTANT_LIST_URL, wait_until="domcontentloaded")

    print(f"[ReportSync] Waiting for Aura consultant-list response (max 20s)...")
    for _ in range(40):
        if captured:
            break
        page.wait_for_timeout(500)

    page.remove_listener("response", _on_response)

    if not captured:
        print("[ReportSync] No unit members found — consultant may not have a team")

    return captured


# ---------------------------------------------------------------------------
# Extract cookies from Playwright context for requests calls
# ---------------------------------------------------------------------------

def _get_cookies_dict(page: Page, target_host: str = "applications.marykayintouch.com") -> dict:
    """
    Return only the cookies that a browser would send to target_host.
    Filters to exact-domain cookies and wildcard (.domain) cookies that cover
    target_host — prevents host-specific cookies from other subdomains (mk., apps.,
    order.) from overwriting the correct wildcard-domain values in the flat dict.
    """
    all_cookies = page.context.cookies()
    result = {}
    for c in all_cookies:
        domain = c.get("domain", "")
        is_exact = (domain == target_host)
        is_wildcard = domain.startswith(".") and target_host.endswith(domain)
        if is_exact or is_wildcard:
            result[c["name"]] = c["value"]
    return result


# ---------------------------------------------------------------------------
# FOReports API helper
# ---------------------------------------------------------------------------

def _foreposts_get(cookies: dict, report_id: str, parameters: dict) -> list[dict]:
    params_encoded = urllib.parse.quote(json.dumps(parameters))
    url = f"{_FOREPORTS_BASE}/report?id={report_id}&parameters={params_encoded}"
    try:
        resp = requests.get(url, cookies=cookies, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        print(f"[ReportSync] {report_id} unexpected response type: {type(data)}")
        return []
    except Exception as e:
        print(f"[ReportSync] {report_id} fetch error: {e}")
        return []


# ---------------------------------------------------------------------------
# Data mappers
# ---------------------------------------------------------------------------

def _map_unit_member(raw: dict, consultant_id: int) -> dict:
    mailing = raw.get("MailingAddress") or {}
    _shops_raw = raw.get("Shops__r")
    shops = (_shops_raw[0] if isinstance(_shops_raw, list) and _shops_raw else
             _shops_raw if isinstance(_shops_raw, dict) else None)
    account = raw.get("Account") or {}
    # None = no shop record in InTouch (never created) → treat as inactive (0)
    if shops is None:
        myshop_active = 0
    else:
        myshop = shops.get("IsShopActive_cb__c")
        myshop_active = 1 if myshop is True else 0
    return {
        "consultant_id":        consultant_id,
        "intouch_contact_id":   raw.get("Id", ""),
        "consultant_number":    raw.get("ConsultantNumber__c"),
        "first_name":           raw.get("FirstName"),
        "last_name":            raw.get("LastName"),
        "email":                raw.get("Email"),
        "phone":                raw.get("Phone") or raw.get("HomePhone"),
        "address":              mailing.get("street"),
        "city":                 mailing.get("city"),
        "state":                mailing.get("stateCode") or mailing.get("state"),
        "zip":                  mailing.get("postalCode"),
        "career_level_code":    raw.get("CareerLevelCode_p__c"),
        "career_level_desc":    raw.get("CareerLevelShortDescription_p__c"),
        "activity_status":      raw.get("ActivityStatusCode_p__c"),
        "language":             raw.get("LanguagePreference__c"),
        "myshop_active":        myshop_active,
        "birthday":             raw.get("Birthdate_d__c"),
        "start_date":           account.get("StartDate__c"),
        "last_order_date":      account.get("LastOrderDate_d__c"),
        "last_order_wholesale": account.get("LastOrderWholesaleAmount_cr__c"),
        "last_order_retail":    account.get("LastOrderRetailAmount_cr__c"),
        "unit_number":          raw.get("UnitNumber__c"),
        "segments":             raw.get("Segments_mp__c"),
        "recruiter_info":       raw.get("RecruiterContactInfo_f__c"),
        "synced_at":            datetime.utcnow().isoformat(),
    }


def _map_great_start(raw: dict, consultant_id: int, month_key: str) -> dict:
    return {
        "consultant_id":      consultant_id,
        "consultant_number":  str(raw.get("consultantNumber") or raw.get("consultantKey") or ""),
        "total_bundles":      raw.get("totalBundles"),
        "needed_next_bundle": raw.get("neededNextBundle"),
        "promotion_end_date": raw.get("promotionEndDate"),
        "total_production":   raw.get("totalPromotionProduction"),
        "rsks_bundles":       raw.get("totalRSKSBundles"),
        "rsks_production_left": raw.get("totalRSKSProductionLeft"),
        "production_month_key": month_key,
        "synced_at":          datetime.utcnow().isoformat(),
    }


def _map_rise_radiate(raw: dict, consultant_id: int) -> dict:
    def _iso(val):
        if not val:
            return None
        return str(val)[:10]  # trim to YYYY-MM-DD
    return {
        "consultant_id":      consultant_id,
        "intouch_contact_id": raw.get("contactID"),
        "consultant_number":  str(raw.get("consultantNumber") or raw.get("consultantKey") or ""),
        "contest_goal":       raw.get("contestGoal"),
        "amount_needed":      raw.get("amountNeededToReachContestGoal"),
        "challenge_count":    raw.get("challengeCount"),
        "month0_production":  raw.get("month0ProductionAmount"),
        "month1_production":  raw.get("month1ProductionAmount"),
        "month2_production":  raw.get("month2ProductionAmount"),
        "month3_production":  raw.get("month3ProductionAmount"),
        "month4_production":  raw.get("month4ProductionAmount"),
        "month5_production":  raw.get("month5ProductionAmount"),
        "display_month0":     _iso(raw.get("displayMonth0")),
        "display_month1":     _iso(raw.get("displayMonth1")),
        "display_month2":     _iso(raw.get("displayMonth2")),
        "display_month3":     _iso(raw.get("displayMonth3")),
        "display_month4":     _iso(raw.get("displayMonth4")),
        "display_month5":     _iso(raw.get("displayMonth5")),
        "synced_at":          datetime.utcnow().isoformat(),
    }


def _map_star_tracking(raw: dict, consultant_id: int) -> dict:
    return {
        "consultant_id":      consultant_id,
        "consultant_number":  str(raw.get("consultantNumber") or raw.get("consultantKey") or ""),
        "contest_amount":     raw.get("contestAmount"),
        "level_achieved":     raw.get("levelAchieved"),
        "level_name":         raw.get("levelName"),
        "needed_ruby":        raw.get("contestAmountNeededRuby"),
        "needed_diamond":     raw.get("contestAmountNeededDiamond"),
        "needed_emerald":     raw.get("contestAmountNeededEmerald"),
        "needed_pearl":       raw.get("contestAmountNeededPearl"),
        "contest_begin_date": raw.get("contestBeginDate"),
        "contest_end_date":   raw.get("contestEndDate"),
        "total_star_quarters": raw.get("totalStarQuarters"),
        "synced_at":          datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# DB upserts (SQLite + Postgres compatible via placeholder swap)
# ---------------------------------------------------------------------------

def _snapshot_unit_member_activity(cur, members: list[dict], ph: str) -> None:
    if not members:
        return
    from datetime import datetime
    period_month = datetime.utcnow().strftime("%Y-%m")
    consultant_id = members[0]["consultant_id"]

    # Fetch the most recent prior-month snapshot for each unit member so we can
    # detect non-A → A transitions and record the activation date.
    cur.execute(f"""
        SELECT consultant_number, activity_status, last_activated_date
        FROM (
            SELECT consultant_number, activity_status, last_activated_date,
                   ROW_NUMBER() OVER (PARTITION BY consultant_number ORDER BY period_month DESC) AS rn
            FROM unit_member_activity_history
            WHERE consultant_id = {ph} AND period_month < {ph}
        ) t WHERE rn = 1
    """, (consultant_id, period_month))
    prior = {row[0]: {"status": row[1], "last_activated_date": row[2]} for row in cur.fetchall()}

    sql = f"""
        INSERT INTO unit_member_activity_history
          (consultant_id, consultant_number, period_month,
           activity_status, last_order_retail, last_order_wholesale,
           career_level_code, career_level_desc, myshop_active,
           last_activated_date, synced_at)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        ON CONFLICT (consultant_id, consultant_number, period_month) DO UPDATE SET
          activity_status      = excluded.activity_status,
          last_order_retail    = excluded.last_order_retail,
          last_order_wholesale = excluded.last_order_wholesale,
          career_level_code    = excluded.career_level_code,
          career_level_desc    = excluded.career_level_desc,
          myshop_active        = excluded.myshop_active,
          last_activated_date  = COALESCE(excluded.last_activated_date,
                                          unit_member_activity_history.last_activated_date),
          synced_at            = excluded.synced_at
    """
    for m in members:
        cnum = m.get("consultant_number")
        current_status = m.get("activity_status") or ""
        prior_info = prior.get(cnum, {})
        prior_status = prior_info.get("status") or ""
        prior_activated = prior_info.get("last_activated_date")

        # Set last_activated_date whenever status becomes A1 from anything other than A1.
        # This covers both fresh activations (I*/T* → A1) and reactivations (A2/A3 → A1).
        if current_status == "A1" and prior_status != "A1":
            last_activated_date = m.get("last_order_date")
        else:
            last_activated_date = prior_activated

        cur.execute(sql, (
            consultant_id, cnum, period_month,
            current_status, m.get("last_order_retail"), m.get("last_order_wholesale"),
            m.get("career_level_code"), m.get("career_level_desc"), m.get("myshop_active"),
            last_activated_date, m.get("synced_at"),
        ))
    print(f"[ReportSync] Snapshotted {len(members)} activity records for {period_month}")


def _upsert_unit_members(cur, members: list[dict], ph: str) -> int:
    if not members:
        return 0
    sql = f"""
        INSERT INTO unit_members
          (consultant_id, intouch_contact_id, consultant_number,
           first_name, last_name, email, phone,
           address, city, state, zip,
           career_level_code, career_level_desc, activity_status,
           language, myshop_active, birthday, start_date,
           last_order_date, last_order_wholesale, last_order_retail,
           unit_number, segments, recruiter_info, sync_status, synced_at)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},'active',{ph})
        ON CONFLICT (consultant_id, intouch_contact_id) DO UPDATE SET
          consultant_number    = excluded.consultant_number,
          first_name           = excluded.first_name,
          last_name            = excluded.last_name,
          email                = excluded.email,
          phone                = excluded.phone,
          address              = excluded.address,
          city                 = excluded.city,
          state                = excluded.state,
          zip                  = excluded.zip,
          career_level_code    = excluded.career_level_code,
          career_level_desc    = excluded.career_level_desc,
          activity_status      = excluded.activity_status,
          language             = excluded.language,
          myshop_active        = excluded.myshop_active,
          birthday             = excluded.birthday,
          start_date           = excluded.start_date,
          last_order_date      = excluded.last_order_date,
          last_order_wholesale = excluded.last_order_wholesale,
          last_order_retail    = excluded.last_order_retail,
          unit_number          = excluded.unit_number,
          segments             = excluded.segments,
          recruiter_info       = excluded.recruiter_info,
          sync_status          = 'active',
          synced_at            = excluded.synced_at
    """
    consultant_id = members[0]["consultant_id"]
    for m in members:
        cur.execute(sql, (
            m["consultant_id"], m["intouch_contact_id"], m["consultant_number"],
            m["first_name"], m["last_name"], m["email"], m["phone"],
            m["address"], m["city"], m["state"], m["zip"],
            m["career_level_code"], m["career_level_desc"], m["activity_status"],
            m["language"], m["myshop_active"], m["birthday"], m["start_date"],
            m["last_order_date"], m["last_order_wholesale"], m["last_order_retail"],
            m["unit_number"], m["segments"], m["recruiter_info"], m["synced_at"],
        ))

    # Mark anyone not in this sync as removed — they're no longer on InTouch
    current_numbers = [m["consultant_number"] for m in members if m["consultant_number"]]
    if current_numbers:
        placeholders = ",".join([ph] * len(current_numbers))
        cur.execute(
            f"UPDATE unit_members SET sync_status = 'removed' "
            f"WHERE consultant_id = {ph} AND sync_status = 'active' "
            f"AND consultant_number NOT IN ({placeholders})",
            [consultant_id] + current_numbers,
        )
        removed = cur.rowcount
        if removed:
            print(f"[ReportSync] Marked {removed} consultant(s) as removed (no longer in InTouch)")

    return len(members)


def _upsert_great_start(cur, records: list[dict], ph: str) -> int:
    if not records:
        return 0
    sql = f"""
        INSERT INTO unit_great_start
          (consultant_id, consultant_number,
           total_bundles, needed_next_bundle, promotion_end_date,
           total_production, rsks_bundles, rsks_production_left,
           production_month_key, synced_at)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        ON CONFLICT (consultant_id, consultant_number) DO UPDATE SET
          total_bundles         = excluded.total_bundles,
          needed_next_bundle    = excluded.needed_next_bundle,
          promotion_end_date    = excluded.promotion_end_date,
          total_production      = excluded.total_production,
          rsks_bundles          = excluded.rsks_bundles,
          rsks_production_left  = excluded.rsks_production_left,
          production_month_key  = excluded.production_month_key,
          synced_at             = excluded.synced_at
    """
    for r in records:
        cur.execute(sql, (
            r["consultant_id"], r["consultant_number"],
            r["total_bundles"], r["needed_next_bundle"], r["promotion_end_date"],
            r["total_production"], r["rsks_bundles"], r["rsks_production_left"],
            r["production_month_key"], r["synced_at"],
        ))
    return len(records)


def _upsert_rise_radiate(cur, records: list[dict], ph: str) -> int:
    if not records:
        return 0
    sql = f"""
        INSERT INTO unit_rise_radiate
          (consultant_id, intouch_contact_id, consultant_number,
           contest_goal, amount_needed, challenge_count,
           month0_production, month1_production, month2_production,
           month3_production, month4_production, month5_production,
           display_month0, display_month1, display_month2,
           display_month3, display_month4, display_month5,
           synced_at)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        ON CONFLICT (consultant_id, consultant_number) DO UPDATE SET
          intouch_contact_id = excluded.intouch_contact_id,
          contest_goal       = excluded.contest_goal,
          amount_needed      = excluded.amount_needed,
          challenge_count    = excluded.challenge_count,
          month0_production  = excluded.month0_production,
          month1_production  = excluded.month1_production,
          month2_production  = excluded.month2_production,
          month3_production  = excluded.month3_production,
          month4_production  = excluded.month4_production,
          month5_production  = excluded.month5_production,
          display_month0     = excluded.display_month0,
          display_month1     = excluded.display_month1,
          display_month2     = excluded.display_month2,
          display_month3     = excluded.display_month3,
          display_month4     = excluded.display_month4,
          display_month5     = excluded.display_month5,
          synced_at          = excluded.synced_at
    """
    for r in records:
        cur.execute(sql, (
            r["consultant_id"], r["intouch_contact_id"], r["consultant_number"],
            r["contest_goal"], r["amount_needed"], r["challenge_count"],
            r["month0_production"], r["month1_production"], r["month2_production"],
            r["month3_production"], r["month4_production"], r["month5_production"],
            r["display_month0"], r["display_month1"], r["display_month2"],
            r["display_month3"], r["display_month4"], r["display_month5"],
            r["synced_at"],
        ))
    return len(records)


def _fetch_seminar_event_key(cookies: dict) -> tuple[int | None, str | None, str | None]:
    """
    Fetch the upcoming Seminar event key from registration-events.
    Returns (event_key, event_name, begin_date_iso) for the next in-person Seminar,
    or (None, None, None) if not found.
    """
    url = f"{_FOREPORTS_BASE}/report?id=registration-events"
    try:
        resp = requests.get(url, cookies=cookies, timeout=30)
        resp.raise_for_status()
        events = resp.json()
        if not isinstance(events, list):
            return None, None, None
        today = date.today().isoformat()
        # Find the next in-person Seminar (eventCode "SM") with a future or current begin date
        seminars = [
            e for e in events
            if (e.get("eventCode") or "").strip() == "SM"
            and str(e.get("beginDate") or "")[:10] >= today[:4]  # same year or future
        ]
        # Take the most recent one (closest to today)
        seminars.sort(key=lambda e: e.get("beginDate") or "")
        for s in seminars:
            return s["eventKey"], s["eventName"], str(s["beginDate"])[:10]
    except Exception as e:
        print(f"[ReportSync] registration-events fetch error: {e}")
    return None, None, None


def _upsert_registrations(cur, records: list[dict], ph: str) -> int:
    if not records:
        return 0
    sql = f"""
        INSERT INTO unit_registrations
          (consultant_id, intouch_contact_id, consultant_number,
           event_key, event_name, event_begin_date,
           registered_count, wait_list_count,
           guest_registered_count, guest_wait_list_count,
           registered_status, synced_at)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        ON CONFLICT (consultant_id, consultant_number, event_key) DO UPDATE SET
          intouch_contact_id     = excluded.intouch_contact_id,
          event_name             = excluded.event_name,
          event_begin_date       = excluded.event_begin_date,
          registered_count       = excluded.registered_count,
          wait_list_count        = excluded.wait_list_count,
          guest_registered_count = excluded.guest_registered_count,
          guest_wait_list_count  = excluded.guest_wait_list_count,
          registered_status      = excluded.registered_status,
          synced_at              = excluded.synced_at
    """
    for r in records:
        cur.execute(sql, (
            r["consultant_id"], r["intouch_contact_id"], r["consultant_number"],
            r["event_key"], r["event_name"], r["event_begin_date"],
            r["registered_count"], r["wait_list_count"],
            r["guest_registered_count"], r["guest_wait_list_count"],
            r["registered_status"], r["synced_at"],
        ))
    return len(records)


def _upsert_star_tracking(cur, records: list[dict], ph: str) -> int:
    if not records:
        return 0
    sql = f"""
        INSERT INTO unit_star_tracking
          (consultant_id, consultant_number,
           contest_amount, level_achieved, level_name,
           needed_ruby, needed_diamond, needed_emerald, needed_pearl,
           contest_begin_date, contest_end_date, total_star_quarters, synced_at)
        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
        ON CONFLICT (consultant_id, consultant_number) DO UPDATE SET
          contest_amount     = excluded.contest_amount,
          level_achieved     = excluded.level_achieved,
          level_name         = excluded.level_name,
          needed_ruby        = excluded.needed_ruby,
          needed_diamond     = excluded.needed_diamond,
          needed_emerald     = excluded.needed_emerald,
          needed_pearl       = excluded.needed_pearl,
          contest_begin_date = excluded.contest_begin_date,
          contest_end_date   = excluded.contest_end_date,
          total_star_quarters = excluded.total_star_quarters,
          synced_at          = excluded.synced_at
    """
    for r in records:
        cur.execute(sql, (
            r["consultant_id"], r["consultant_number"],
            r["contest_amount"], r["level_achieved"], r["level_name"],
            r["needed_ruby"], r["needed_diamond"], r["needed_emerald"], r["needed_pearl"],
            r["contest_begin_date"], r["contest_end_date"], r["total_star_quarters"],
            r["synced_at"],
        ))
    return len(records)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_report_sync(page: Page, cur, consultant_id: int, ph: str = "?") -> dict:
    """
    Run a full report sync for one consultant. Assumes login_intouch() already ran.
    Returns a summary dict with counts.
    """
    # Step 1: unit members (Aura interception)
    raw_members = fetch_unit_members(page)
    if not raw_members:
        return {"members": 0, "great_start": 0, "star_tracking": 0}

    mapped_members = [_map_unit_member(r, consultant_id) for r in raw_members]
    members_count = _upsert_unit_members(cur, mapped_members, ph)
    print(f"[ReportSync] Upserted {members_count} unit_members")

    # Snapshot current-month activity for historical tracking
    _snapshot_unit_member_activity(cur, mapped_members, ph)

    # Mark personal recruits: look up the consultant's own email, then flag anyone
    # whose recruiter_info contains that email address (reliable structured match).
    from db import connect as _connect
    _email_conn = _connect()
    try:
        _ec = _email_conn.cursor()
        _ec.execute(f"SELECT email FROM consultants WHERE id = {ph}", (consultant_id,))
        _row = _ec.fetchone()
        _owner_email = (_row["email"] if hasattr(_row, "keys") else _row[0]) if _row else None
    finally:
        _email_conn.close()

    if _owner_email:
        cur.execute(
            f"UPDATE unit_members SET is_personal_recruit = 1 "
            f"WHERE consultant_id = {ph} AND recruiter_info LIKE {ph}",
            (consultant_id, f"%Email: {_owner_email}%"),
        )
        cur.execute(
            f"UPDATE unit_members SET is_personal_recruit = 0 "
            f"WHERE consultant_id = {ph} AND (recruiter_info NOT LIKE {ph} OR recruiter_info IS NULL)",
            (consultant_id, f"%Email: {_owner_email}%"),
        )
        personal_count = sum(1 for m in mapped_members
                             if _owner_email.lower() in (m.get("recruiter_info") or "").lower())
        print(f"[ReportSync] Marked {personal_count} personal recruits (owner={_owner_email})")

    # Step 2: extract session cookies for FOReports calls
    # Domain-filtered to only cookies valid for applications.marykayintouch.com,
    # preventing host-specific cookies from other subdomains clobbering the right values
    cookies = _get_cookies_dict(page)

    # Step 3: great start (new-consultant-promotion-unit)
    month_key = _current_production_month()
    raw_gs = _foreposts_get(cookies, "new-consultant-promotion-unit", {"productionMonth": month_key})
    mapped_gs = [_map_great_start(r, consultant_id, month_key) for r in raw_gs]
    mapped_gs = [r for r in mapped_gs if r["consultant_number"]]
    gs_count = _upsert_great_start(cur, mapped_gs, ph)
    print(f"[ReportSync] Upserted {gs_count} unit_great_start records")

    # Step 4: star tracking (ladder-of-success-current-quarter-unit)
    quarter_date = _current_quarter_date()
    raw_star = _foreposts_get(cookies, "ladder-of-success-current-quarter-unit", {"productionQuarter": quarter_date})
    mapped_star = [_map_star_tracking(r, consultant_id) for r in raw_star]
    mapped_star = [r for r in mapped_star if r["consultant_number"]]
    star_count = _upsert_star_tracking(cur, mapped_star, ph)
    print(f"[ReportSync] Upserted {star_count} unit_star_tracking records")

    # Step 5: Rise + Radiate IBC selling challenge
    raw_rr = _foreposts_get(cookies, "rise-and-radiate-challenge-unit", {})
    mapped_rr = [_map_rise_radiate(r, consultant_id) for r in raw_rr]
    mapped_rr = [r for r in mapped_rr if r["consultant_number"]]
    rr_count = _upsert_rise_radiate(cur, mapped_rr, ph)
    print(f"[ReportSync] Upserted {rr_count} unit_rise_radiate records")

    # Step 6: seminar registration — find current Seminar event, then pull unit registrations
    reg_count = 0
    event_key, event_name, event_begin = _fetch_seminar_event_key(cookies)
    if event_key:
        print(f"[ReportSync] Fetching registrations for {event_name} (key={event_key})")
        raw_reg = _foreposts_get(cookies, "registration-unit", {"EventKey": event_key})
        now = datetime.utcnow().isoformat()
        mapped_reg = []
        for r in raw_reg:
            cn = str(r.get("consultantNumber") or r.get("consultantID") or "")
            if not cn:
                continue
            mapped_reg.append({
                "consultant_id":           consultant_id,
                "intouch_contact_id":      r.get("contactID"),
                "consultant_number":       cn,
                "event_key":               event_key,
                "event_name":              event_name,
                "event_begin_date":        event_begin,
                "registered_count":        r.get("registeredCount") or 0,
                "wait_list_count":         r.get("waitListCount") or 0,
                "guest_registered_count":  r.get("guestRegisteredCount") or 0,
                "guest_wait_list_count":   r.get("guestWaitListCount") or 0,
                "registered_status":       r.get("registeredStatus"),
                "synced_at":               now,
            })
        reg_count = _upsert_registrations(cur, mapped_reg, ph)
        print(f"[ReportSync] Upserted {reg_count} unit_registrations records")
    else:
        print("[ReportSync] No upcoming Seminar event found — skipping registration sync")

    return {
        "members": members_count,
        "great_start": gs_count,
        "star_tracking": star_count,
        "rise_radiate": rr_count,
        "registrations": reg_count,
    }
