"""Director feature: career car program status, thresholds, co-pay schedule.
"""
import json
import re

from db import connect, is_postgres

from .dbutil import PH
from .types import ChatReply
from .ui_text import UI_EN


_CAR_LEVEL_LABELS = {
    # Maps carAward code prefixes/substrings to display names
    "grandachiever": "Grand Achiever",
    "premierclub":   "Premier Club",
    "cadillac":      "Cadillac",
}

_CAR_THRESHOLDS = {
    # (qual_per_2qtrs, maint_min_per_qtr, copay_max_per_mo)
    "Grand Achiever": (48_000,  23_500, 425),
    "Premier Club":   (66_000,  32_000, 525),
    "Cadillac":       (114_000, 56_000, 925),
}

# Co-op lease payment schedules from MK guidelines (11/2025).
# Each entry is (min_production, monthly_copay) sorted descending.
# Source: program guideline PDFs — amounts subject to change by MK.
_CAR_COPAY_SCHEDULE = {
    "Grand Achiever": [
        (23_500, 0.00),
        (20_500, 42.50),
        (18_500, 85.00),
        (16_500, 127.50),
        (14_500, 212.50),
        (12_500, 297.50),
        (0,      425.00),
    ],
    "Premier Club": [
        (32_000, 0.00),
        (29_000, 52.50),
        (26_000, 105.00),
        (23_000, 157.50),
        (20_000, 262.50),
        (17_000, 367.50),
        (0,      525.00),
    ],
    "Cadillac": [
        (56_000, 0.00),
        (53_000, 92.50),
        (50_000, 185.00),
        (46_000, 277.50),
        (42_000, 462.50),
        (38_000, 647.50),
        (0,      925.00),
    ],
}


def _car_copay_amount(level: str, production: float | None) -> float | None:
    schedule = _CAR_COPAY_SCHEDULE.get(level)
    if not schedule or production is None:
        return None
    for min_prod, monthly in schedule:
        if production >= min_prod:
            return monthly
    return None


def _car_level_display(car_award: str | None, ui: dict = None) -> str:
    if ui is None:
        ui = UI_EN
    if not car_award:
        return ui["car_program_no_award"]
    code = car_award.lower().replace("sd", "").replace("v3", "").replace("v2", "").replace("v1", "")
    for key, label in _CAR_LEVEL_LABELS.items():
        if key in code:
            return label
    return car_award


def _fmt_dollars(val) -> str:
    if val is None:
        return "—"
    return f"${val:,.0f}"


def _handle_car_program(consultant_id: int, msg: str = "", ui: dict = None) -> "ChatReply":
    if ui is None:
        ui = UI_EN
    with connect() as conn:
        cur = conn.cursor()
        PH = "%s" if is_postgres() else "?"
        cur.execute(
            f"SELECT * FROM unit_car_award WHERE consultant_id = {PH}",
            (consultant_id,),
        )
        row = cur.fetchone()
        col_names = [d[0] for d in cur.description] if cur.description else []

    if not row:
        return ChatReply(ui["car_program_no_data"])

    if hasattr(row, "keys"):
        r = dict(row)
    else:
        r = dict(zip(col_names, row))

    synced_at = (r.get("synced_at") or "")[:16].replace("T", " ")
    level = _car_level_display(r.get("car_award"), ui=ui)
    status_desc = r.get("car_status_type_desc") or r.get("car_status_type") or ui["car_program_status_unknown"]
    q0 = r.get("q0_total_car_production")
    q1 = r.get("q1_total_car_production")
    q2 = r.get("q2_total_car_production")
    maint_min = r.get("unit_maint_min_qtr")
    ot_goal = r.get("ot_goal")
    needed_ot = r.get("needed_ot_goal")
    balance = r.get("car_unit_balance") or 0.0
    balance_prev = r.get("car_unit_balance_prev_qtr") or 0.0
    requali_date = (r.get("requalification_date") or "")[:10]

    # Quarter label from display_u_month fields
    m0 = (r.get("display_u_month0") or "")[:7]  # e.g. "2026-06"
    m2 = (r.get("display_u_month2") or "")[:7]  # e.g. "2026-04"

    def _month_abbr(ym: str) -> str:
        if not ym or len(ym) < 7:
            return ym
        try:
            import calendar as _cal
            mo = int(ym[5:7])
            yr = ym[:4]
            return f"{_cal.month_abbr[mo]} {yr}"
        except Exception:
            return ym

    qtr_label = f"{_month_abbr(m2)}–{_month_abbr(m0)}" if m0 and m2 else ui["car_program_current_quarter"]

    def _fmt_date(d: str) -> str:
        if not d or len(d) < 10:
            return d
        try:
            yr, mo, day = d[:10].split("-")
            return f"{mo}-{day}-{yr[2:]}"
        except Exception:
            return d

    lines = [ui["car_program_header"].format(level=level)]
    lines.append(ui["car_program_status"].format(status_desc=status_desc))

    if q0 is not None and maint_min is not None:
        short = maint_min - q0
        lines.append(ui["car_program_production_of_goal"].format(
            qtr_label=qtr_label, q0=_fmt_dollars(q0), maint_min=_fmt_dollars(maint_min)
        ))
        if short > 0:
            lines.append(ui["car_program_remaining"].format(short=_fmt_dollars(short)))
        else:
            lines.append(ui["car_program_goal_met"])
    elif q0 is not None:
        lines.append(ui["car_program_production_only"].format(qtr_label=qtr_label, q0=_fmt_dollars(q0)))

    # Only show on-target as a separate line if it differs from what's already shown above
    if (ot_goal is not None and needed_ot is not None and needed_ot > 0
            and ot_goal != maint_min):
        lines.append(ui["car_program_on_target_goal"].format(
            ot_goal=_fmt_dollars(ot_goal), needed_ot=_fmt_dollars(needed_ot)
        ))

    if q1 is not None:
        lines.append(ui["car_program_last_quarter"].format(q1=_fmt_dollars(q1)))
    if q2 is not None:
        lines.append(ui["car_program_two_quarters_ago"].format(q2=_fmt_dollars(q2)))

    # Co-pay: only shown when the user specifically asks about it
    if re.search(r"\bco[- ]?pay\b", msg, re.IGNORECASE):
        copay = _car_copay_amount(level, q1)
        if copay is None:
            pass
        elif copay > 0:
            lines.append(ui["car_program_copay_amount"].format(copay=f"${copay:,.2f}"))
        else:
            lines.append(ui["car_program_copay_none"])

    if requali_date:
        lines.append(ui["car_program_requal_date"].format(date=_fmt_date(requali_date)))

    return ChatReply("\n".join(lines))
