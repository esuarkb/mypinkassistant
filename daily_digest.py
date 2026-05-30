"""
daily_digest.py

Analyzes yesterday's chat intent logs and emails a summary to Brian.
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


def run():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Yesterday in UTC
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    yesterday_label = yesterday_start.strftime("%B %-d, %Y")

    # ── Pull intent logs for yesterday ──────────────────────────────────────
    cur.execute("""
        SELECT il.consultant_id, il.intent, il.confidence, il.message_text, il.created_at,
               c.first_name, c.last_name
        FROM intent_logs il
        JOIN consultants c ON c.id = il.consultant_id
        WHERE il.created_at >= %s AND il.created_at < %s
        ORDER BY il.created_at
    """, (yesterday_start, today_start))
    rows = cur.fetchall()

    if not rows:
        print(f"No intent logs for {yesterday_label}, skipping email.")
        conn.close()
        return

    # ── New consultants who chatted for the first time ───────────────────────
    cur.execute("""
        SELECT c.id, c.first_name, c.last_name
        FROM consultants c
        WHERE c.created_at >= %s AND c.created_at < %s
    """, (yesterday_start, today_start))
    new_consultants = {r[0]: f"{r[1]} {r[2]}" for r in cur.fetchall()}

    conn.close()

    # ── Stats ────────────────────────────────────────────────────────────────
    total_messages = len(rows)
    consultant_message_counts = Counter(r[0] for r in rows)
    unique_consultants = len(consultant_message_counts)
    intent_counts = Counter(r[1] for r in rows)

    # Most active consultants (top 5)
    consultant_names = {r[0]: f"{r[5]} {r[6]}" for r in rows}
    most_active = [
        (consultant_names[cid], count)
        for cid, count in consultant_message_counts.most_common(5)
    ]

    # New consultants who chatted
    new_who_chatted = [
        consultant_names[cid]
        for cid in consultant_message_counts
        if cid in new_consultants
    ]

    # ── Routing gaps: low confidence or fallback ─────────────────────────────
    LOW_CONFIDENCE = 0.75
    FALLBACK_INTENTS = {"fallback", "unknown", "clarify", "other"}

    gap_messages = [
        r for r in rows
        if (r[2] is not None and r[2] < LOW_CONFIDENCE)
        or r[1].lower() in FALLBACK_INTENTS
    ]

    # ── Repeated attempts: same consultant, 3+ messages within 2 minutes ────
    repeated_attempts = []
    by_consultant = defaultdict(list)
    for r in rows:
        by_consultant[r[0]].append(r)

    for cid, msgs in by_consultant.items():
        msgs_sorted = sorted(msgs, key=lambda x: x[4])
        i = 0
        while i < len(msgs_sorted):
            window = [msgs_sorted[i]]
            j = i + 1
            while j < len(msgs_sorted):
                delta = (msgs_sorted[j][4] - msgs_sorted[i][4]).total_seconds()
                if delta <= 120:
                    window.append(msgs_sorted[j])
                    j += 1
                else:
                    break
            if len(window) >= 3:
                repeated_attempts.append({
                    "name": f"{msgs_sorted[i][5]} {msgs_sorted[i][6]}",
                    "count": len(window),
                    "messages": [w[3] for w in window],
                    "intent": window[0][1],
                })
                i = j
            else:
                i += 1

    # ── OpenAI analysis of gaps ──────────────────────────────────────────────
    ai_analysis = ""
    samples_for_ai = []
    for r in rows:
        if (r[2] is not None and r[2] < LOW_CONFIDENCE) or r[1] in FALLBACK_INTENTS:
            samples_for_ai.append(f"[{r[1]}] {r[3]}")
    for attempt in repeated_attempts:
        for m in attempt["messages"]:
            samples_for_ai.append(f"[repeated/{attempt['intent']}] {m}")

    # Also sample a few random messages for broader context
    import random
    all_texts = [r[3] for r in rows if r[3]]
    random_sample = random.sample(all_texts, min(20, len(all_texts)))
    for t in random_sample:
        if t not in samples_for_ai:
            samples_for_ai.append(f"[sample] {t}")

    if samples_for_ai and OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            prompt = (
                "You are analyzing chat messages sent by Mary Kay consultants to an AI assistant app called MyPinkAssistant. "
                "The app helps them look up customers, place orders, check product prices, run follow-ups, and manage inventory.\n\n"
                "Below are chat messages from yesterday — some flagged as low-confidence routing, some as repeated attempts "
                "(consultant tried multiple times), and some random samples.\n\n"
                "Identify:\n"
                "1. Patterns where consultants seem confused about how to phrase requests\n"
                "2. Things consultants are trying to do that the app probably doesn't support yet (potential features)\n"
                "3. Anything else notable\n\n"
                "Be specific and concise. Use bullet points. Max 200 words.\n\n"
                "Messages:\n" + "\n".join(samples_for_ai[:40])
            )
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.3,
            )
            ai_analysis = resp.choices[0].message.content.strip()
        except Exception as e:
            ai_analysis = f"(AI analysis unavailable: {e})"

    # ── Build email ──────────────────────────────────────────────────────────
    intent_rows_html = "".join(
        f"<tr><td style='padding:2px 12px 2px 0'>{intent}</td><td style='padding:2px 0'><strong>{count}</strong></td></tr>"
        for intent, count in intent_counts.most_common()
    )

    most_active_html = "".join(
        f"<li>{name} ({count} messages)</li>"
        for name, count in most_active
    )

    new_chatted_html = (
        "<li>" + "</li><li>".join(new_who_chatted) + "</li>"
        if new_who_chatted else "<li>None</li>"
    )

    gap_html = ""
    if gap_messages:
        gap_html = "<ul>" + "".join(
            f"<li><strong>{r[5]} {r[6]}</strong>: \"{r[3]}\" → {r[1]} ({r[2]:.0%} confidence)</li>"
            for r in gap_messages[:10]
        ) + "</ul>"
    else:
        gap_html = "<p>None — all messages routed with high confidence.</p>"

    repeated_html = ""
    if repeated_attempts:
        repeated_html = "<ul>"
        for a in repeated_attempts:
            msgs_preview = "; ".join(f'"{m}"' for m in a["messages"][:4])
            repeated_html += f"<li><strong>{a['name']}</strong> sent {a['count']} similar messages: {msgs_preview}</li>"
        repeated_html += "</ul>"
    else:
        repeated_html = "<p>None.</p>"

    ai_html = f"<p>{ai_analysis.replace(chr(10), '<br>')}</p>" if ai_analysis else "<p>No unusual patterns to report.</p>"

    html = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;margin:0 auto;color:#1a1a1a">
      <h2 style="color:#d63384;margin-bottom:4px">MPA Chat Summary</h2>
      <p style="color:#666;margin-top:0">{yesterday_label}</p>

      <h3>Yesterday at a glance</h3>
      <ul>
        <li>{unique_consultants} consultants sent {total_messages} messages</li>
      </ul>

      <h4>Most active</h4>
      <ul>{most_active_html}</ul>

      <h4>New consultants who chatted</h4>
      <ul>{new_chatted_html}</ul>

      <h3>Intent breakdown</h3>
      <table style="border-collapse:collapse">{intent_rows_html}</table>

      <h3>Routing gaps &amp; low confidence</h3>
      {gap_html}

      <h3>Repeated attempts (possible confusion)</h3>
      {repeated_html}

      <h3>AI analysis — gaps &amp; feature signals</h3>
      {ai_html}

      <hr style="margin-top:32px;border:none;border-top:1px solid #eee">
      <p style="color:#999;font-size:12px">MyPinkAssistant daily digest · {now_utc.strftime("%Y-%m-%d %H:%M UTC")}</p>
    </div>
    """

    # ── Send via Resend ──────────────────────────────────────────────────────
    subject = f"MPA Chat Summary — {yesterday_label}"
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
        print(f"Digest sent for {yesterday_label} ({total_messages} messages, {unique_consultants} consultants)")


if __name__ == "__main__":
    run()
