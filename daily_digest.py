"""
daily_digest.py

Emails a daily chat activity table to Brian.
Run via Mac cron at 6am local time: 0 6 * * *
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import psycopg2
import requests
from dotenv import dotenv_values, load_dotenv

load_dotenv()
_prod = dotenv_values(os.path.join(os.path.dirname(__file__), ".env.production"))

DATABASE_URL = _prod.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "support@mypinkassistant.com").strip()
TO_EMAIL = "support@mypinkassistant.com"

# Exclude Andrea (id=2) — Brian's account used for testing
EXCLUDE_CONSULTANT_IDS = (2,)

if not DATABASE_URL:
    print("Missing DATABASE_URL"); sys.exit(1)


def strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text or "").strip()


def run():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    yesterday_label = yesterday_start.strftime("%B %-d, %Y")

    # Pull all intent logs for yesterday, excluding test accounts
    cur.execute("""
        SELECT il.consultant_id, c.first_name, c.last_name,
               il.intent, il.confidence, il.message_text,
               il.response_text, il.created_at
        FROM intent_logs il
        JOIN consultants c ON c.id = il.consultant_id
        WHERE il.created_at >= %s AND il.created_at < %s
          AND il.consultant_id != ALL(%s)
        ORDER BY c.last_name, c.first_name, il.created_at
    """, (yesterday_start, today_start, list(EXCLUDE_CONSULTANT_IDS)))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"No intent logs for {yesterday_label}, skipping.")
        return

    total = len(rows)
    unique_consultants = len({r[0] for r in rows})

    # ── Build chat log table ─────────────────────────────────────────────────
    table_rows_html = ""
    prev_consultant = None
    for r in rows:
        cid, first, last, intent, conf, msg_text, response, created_at = r
        name = f"{first} {last}"
        time_str = created_at.astimezone(timezone(timedelta(hours=-5))).strftime("%-I:%M %p")

        low_conf = conf is not None and conf < 0.75
        row_bg = "background:#fff3cd;" if intent in ("unknown", "fallback") or low_conf else ""

        name_cell = f"<strong>{name}</strong>" if name != prev_consultant else ""
        prev_consultant = name

        clean_response = strip_html(response)[:120] if response else "—"
        conf_str = f"{conf:.0%}" if conf is not None else "—"

        table_rows_html += f"""
        <tr style="{row_bg}border-bottom:1px solid #f0f0f0">
          <td style="padding:6px 10px;vertical-align:top;white-space:nowrap;color:#666;font-size:12px">{time_str}</td>
          <td style="padding:6px 10px;vertical-align:top;font-size:13px">{name_cell}</td>
          <td style="padding:6px 10px;vertical-align:top;font-size:13px">{msg_text or '—'}</td>
          <td style="padding:6px 10px;vertical-align:top;font-size:12px;color:#555">{clean_response}</td>
          <td style="padding:6px 10px;vertical-align:top;white-space:nowrap;font-size:12px;color:#888">{intent or '—'}<br><span style="color:#bbb">{conf_str}</span></td>
        </tr>"""

    html = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:0 auto;color:#1a1a1a">
      <h2 style="color:#d63384;margin-bottom:4px">MPA Chat Log</h2>
      <p style="color:#666;margin-top:0">{yesterday_label} &nbsp;·&nbsp; {total} messages &nbsp;·&nbsp; {unique_consultants} consultants</p>

      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead>
          <tr style="background:#f8f8f8;border-bottom:2px solid #ddd">
            <th style="padding:6px 10px;text-align:left;font-size:12px;color:#888">Time (CST)</th>
            <th style="padding:6px 10px;text-align:left">Consultant</th>
            <th style="padding:6px 10px;text-align:left">Message</th>
            <th style="padding:6px 10px;text-align:left">Response</th>
            <th style="padding:6px 10px;text-align:left">Intent</th>
          </tr>
        </thead>
        <tbody>
          {table_rows_html}
        </tbody>
      </table>

      <hr style="margin-top:32px;border:none;border-top:1px solid #eee">
      <p style="color:#999;font-size:11px">Highlighted rows = unknown intent or low confidence · {now_utc.strftime("%Y-%m-%d %H:%M UTC")}</p>
    </div>
    """

    subject = f"MPA Chat Log — {yesterday_label} ({total} messages, {unique_consultants} consultants)"
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={"from": MAIL_FROM, "to": [TO_EMAIL], "subject": subject, "html": html},
        timeout=15,
    )
    if resp.status_code >= 300:
        print(f"Resend error {resp.status_code}: {resp.text}")
        sys.exit(1)
    else:
        print(f"Digest sent for {yesterday_label} ({total} messages, {unique_consultants} consultants)")


if __name__ == "__main__":
    run()
