"""
daily_digest.py

Emails a daily chat activity table to Brian.
Run via Mac cron at 6am local time: 0 6 * * *
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

import psycopg2
import requests
from dotenv import dotenv_values, load_dotenv
from openai import OpenAI

load_dotenv()
_prod = dotenv_values(os.path.join(os.path.dirname(__file__), ".env.production"))

DATABASE_URL = _prod.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "support@mypinkassistant.com").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
TO_EMAIL = "briankrause@gmail.com"

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

    # Pull all intent logs for yesterday with consultant name
    cur.execute("""
        SELECT il.consultant_id, c.first_name, c.last_name,
               il.intent, il.confidence, il.message_text,
               il.response_text, il.created_at
        FROM intent_logs il
        JOIN consultants c ON c.id = il.consultant_id
        WHERE il.created_at >= %s AND il.created_at < %s
        ORDER BY c.last_name, c.first_name, il.created_at
    """, (yesterday_start, today_start))
    rows = cur.fetchall()

    if not rows:
        print(f"No intent logs for {yesterday_label}, skipping.")
        conn.close()
        return

    total = len(rows)
    unique_consultants = len({r[0] for r in rows})
    intent_counts = Counter(r[3] for r in rows)
    unknown_count = sum(v for k, v in intent_counts.items() if k in ("unknown", "fallback"))

    # New consultants who chatted
    cur.execute("""
        SELECT DISTINCT il.consultant_id, c.first_name, c.last_name
        FROM intent_logs il
        JOIN consultants c ON c.id = il.consultant_id
        WHERE il.created_at >= %s AND il.created_at < %s
          AND c.created_at >= %s
    """, (yesterday_start, today_start, yesterday_start - timedelta(days=7)))
    new_chatters = [f"{r[1]} {r[2]}" for r in cur.fetchall()]

    conn.close()

    # ── AI analysis of gaps ──────────────────────────────────────────────────
    ai_analysis = ""
    gap_rows = [r for r in rows if r[3] in ("unknown", "fallback") or (r[4] is not None and r[4] < 0.75)]
    if gap_rows and OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            samples = [f'"{r[5]}" → {r[3]}' for r in gap_rows[:30]]
            prompt = (
                "You are analyzing failed or low-confidence chat messages from Mary Kay consultants "
                "using an AI assistant app. The app handles: customer lookups, orders, product prices, "
                "followups, top customers, lapsed customers, top sellers, city searches.\n\n"
                "Below are messages that didn't route well. In 3-5 bullet points, identify patterns "
                "and suggest what features or phrasings to add. Be specific and concise.\n\n"
                + "\n".join(samples)
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.3,
            )
            ai_analysis = resp.choices[0].message.content.strip()
        except Exception as e:
            ai_analysis = f"(unavailable: {e})"

    # ── Build header stats ───────────────────────────────────────────────────
    intent_summary = " &nbsp;·&nbsp; ".join(
        f"{intent}: {count}" for intent, count in intent_counts.most_common(6)
    )

    new_chatters_html = (
        " &nbsp;·&nbsp; ".join(new_chatters) if new_chatters else "none"
    )

    # ── Build 4-column table ─────────────────────────────────────────────────
    row_styles = {
        "unknown": "background:#fff3cd",
        "fallback": "background:#fff3cd",
    }

    table_rows_html = ""
    prev_consultant = None
    for r in rows:
        cid, first, last, intent, conf, msg_text, response, created_at = r
        name = f"{first} {last}"
        time_str = created_at.astimezone(timezone(timedelta(hours=-5))).strftime("%-I:%M %p")

        # Shade unknown/fallback rows
        low_conf = conf is not None and conf < 0.75
        row_bg = ""
        if intent in ("unknown", "fallback") or low_conf:
            row_bg = "background:#fff3cd;"

        # Bold first row per consultant
        name_cell = ""
        if name != prev_consultant:
            name_cell = f"<strong>{name}</strong>"
            prev_consultant = name
        else:
            name_cell = ""

        clean_response = strip_html(response)[:120] if response else "—"
        conf_str = f"{conf:.0%}" if conf is not None else "—"
        intent_display = intent if intent else "—"

        table_rows_html += f"""
        <tr style="{row_bg}border-bottom:1px solid #f0f0f0">
          <td style="padding:6px 10px;vertical-align:top;white-space:nowrap;color:#666;font-size:12px">{time_str}</td>
          <td style="padding:6px 10px;vertical-align:top;font-size:13px">{name_cell}</td>
          <td style="padding:6px 10px;vertical-align:top;font-size:13px">{msg_text or '—'}</td>
          <td style="padding:6px 10px;vertical-align:top;font-size:12px;color:#555">{clean_response}</td>
          <td style="padding:6px 10px;vertical-align:top;white-space:nowrap;font-size:12px;color:#888">{intent_display}<br><span style="color:#bbb">{conf_str}</span></td>
        </tr>"""

    ai_html = (
        "<ul>" + "".join(f"<li>{line.lstrip('•- ')}</li>" for line in ai_analysis.split("\n") if line.strip()) + "</ul>"
        if ai_analysis else "<p>No gaps detected.</p>"
    )

    html = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:0 auto;color:#1a1a1a">
      <h2 style="color:#d63384;margin-bottom:4px">MPA Chat Log</h2>
      <p style="color:#666;margin-top:0">{yesterday_label} &nbsp;·&nbsp; {total} messages &nbsp;·&nbsp; {unique_consultants} consultants &nbsp;·&nbsp; {unknown_count} unrouted</p>

      <p style="font-size:13px;color:#555"><strong>Intents:</strong> {intent_summary}</p>
      <p style="font-size:13px;color:#555"><strong>New consultants who chatted:</strong> {new_chatters_html}</p>

      {"<h3 style='color:#d63384'>⚠ Gap Analysis</h3>" + ai_html if ai_analysis else ""}

      <h3>Full Chat Log</h3>
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
