# send_pink_post.py
# Sends "The Pink Post", the weekly consultant newsletter.
#
# Usage:
#   python send_pink_post.py --test                 # Brian's inbox only (weekly proof)
#   python send_pink_post.py --dry-run              # list recipients, send nothing
#   python send_pink_post.py --send                 # real send (types SEND to confirm)
#   python send_pink_post.py --send --issue emails/pink_post/2026-08-04.html
#
# Issues live in emails/pink_post/YYYY-MM-DD.html and are self-contained: the
# subject line is the first "<!-- subject: ... -->" comment in the file, so a new
# issue never requires editing this script. With no --issue, the newest file in
# that directory wins.
#
# Each issue carries two tokens, {{FIRST_NAME}} and {{UNSUB_URL}}, substituted
# here IN PYTHON before the Resend call. Resend does NOT substitute placeholders
# on a plain send -- that is exactly how an earlier campaign leaked a raw {name}
# into 70 inboxes -- so every rendered email is verified token-free before it is
# handed over, and any recipient that fails verification is skipped, not sent.

import glob
import hashlib
import hmac
import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()  # RESEND_API_KEY, MAIL_FROM, MK_SESSION_SECRET

# Pull DATABASE_URL from .env.production without overriding the keys above
try:
    for line in open(".env.production").read().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            if k.strip() == "DATABASE_URL":
                os.environ.setdefault("DATABASE_URL", v.strip())
except FileNotFoundError:
    pass

from db import connect, is_postgres  # noqa: E402

TEST_MODE = "--test" in sys.argv
DRY_RUN = "--dry-run" in sys.argv
SEND = "--send" in sys.argv

PH = "%s" if is_postgres() else "?"
RESEND_API_KEY = (os.getenv("RESEND_API_KEY") or "").strip()
MAIL_FROM = (os.getenv("MAIL_FROM") or "").strip()
SESSION_SECRET = (os.getenv("MK_SESSION_SECRET") or "").strip()
APP_BASE_URL = "https://mypinkassistant.com"

# Brian's own inbox, for the weekly proof. cid 1 is the DEMO account and carries
# this same address, which is why the recipient query excludes it -- otherwise
# every customer send would also hit Brian.
TEST_TO = "briankrause@gmail.com"
TEST_NAME = "Brian"
DEMO_CONSULTANT_ID = 1

if not (TEST_MODE or DRY_RUN or SEND):
    sys.exit(__doc__ or "Pass one of --test, --dry-run, --send.")
if not RESEND_API_KEY or not MAIL_FROM:
    sys.exit("Missing RESEND_API_KEY or MAIL_FROM in .env")
if not SESSION_SECRET:
    sys.exit("Missing MK_SESSION_SECRET in .env (needed for the unsubscribe token)")


def pick_issue() -> str:
    if "--issue" in sys.argv:
        return sys.argv[sys.argv.index("--issue") + 1]
    found = sorted(glob.glob("emails/pink_post/*.html"))
    if not found:
        sys.exit("No issues found in emails/pink_post/")
    return found[-1]


ISSUE_PATH = pick_issue()
RAW = open(ISSUE_PATH, encoding="utf-8").read()

_subject = re.search(r"<!--\s*subject:\s*(.+?)\s*-->", RAW)
if not _subject:
    sys.exit(f"{ISSUE_PATH} has no '<!-- subject: ... -->' line")
SUBJECT = _subject.group(1)


def unsub_url(email: str) -> str:
    token = hmac.new(SESSION_SECRET.encode(), email.lower().encode(),
                     hashlib.sha256).hexdigest()
    return f"{APP_BASE_URL}/unsubscribe?email={requests.utils.quote(email)}&token={token}"


def render(first_name: str, email: str) -> str:
    """Substitute tokens and prove none survived. Raises on any problem so the
    caller skips this recipient rather than sending something broken."""
    fname = (first_name or "").strip() or "there"
    html = RAW.replace("{{FIRST_NAME}}", fname).replace("{{UNSUB_URL}}", unsub_url(email))

    problems = []
    if f"Hi {fname}!" not in html:
        problems.append("greeting did not render")
    if leftovers := re.findall(r"\{\{.*?\}\}", html):
        problems.append(f"unsubstituted tokens {sorted(set(leftovers))}")
    for tok in ("{name}", "{first_name}"):
        if tok in html:
            problems.append(f"placeholder {tok!r} present")
    if 'href="#"' in html:
        problems.append("unsubscribe link has no real URL")
    if problems:
        raise ValueError("; ".join(problems))
    return html


def recipients() -> list:
    """Paying/trialing consultants who haven't opted out. Andrea (cid 2) is
    included on purpose -- she reads these. The demo account is excluded."""
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, email, first_name
        FROM consultants
        WHERE billing_status IN ('active', 'trialing')
          AND (email_opted_out IS NULL OR email_opted_out = 0)
          AND id <> {PH}
          AND email IS NOT NULL AND TRIM(email) <> ''
        ORDER BY id
    """, (DEMO_CONSULTANT_ID,))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        keyed = hasattr(r, "keys")
        out.append((
            r["id"] if keyed else r[0],
            (r["email"] if keyed else r[1]).strip(),
            ((r["first_name"] if keyed else r[2]) or "").strip() or "there",
        ))
    return out


def deliver(email: str, first_name: str) -> None:
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        json={"from": MAIL_FROM, "to": [email], "subject": SUBJECT,
              "html": render(first_name, email)},
        timeout=20,
    )
    resp.raise_for_status()


print(f"issue   : {ISSUE_PATH}")
print(f"subject : {SUBJECT}")
print(f"from    : {MAIL_FROM}\n")

if TEST_MODE:
    print(f"TEST SEND -> {TEST_TO} ({TEST_NAME})")
    render(TEST_NAME, TEST_TO)  # raises before anything is sent
    deliver(TEST_TO, TEST_NAME)
    print("  ✓ sent")
    sys.exit(0)

people = recipients()
print(f"{len(people)} recipient(s)"
      f"{' — DRY RUN, nothing will be sent' if DRY_RUN else ''}:\n")
for cid, email, fname in people:
    print(f"  [{cid:>4}] {email:<40} ({fname})")

if DRY_RUN:
    sys.exit(0)

# Verify EVERY email renders cleanly before a single one goes out.
print("\nverifying renders...")
bad = []
for cid, email, fname in people:
    try:
        render(fname, email)
    except ValueError as e:
        bad.append((cid, email, str(e)))
if bad:
    print(f"  ✗ {len(bad)} would render badly — fix before sending:")
    for cid, email, why in bad:
        print(f"      [{cid}] {email}: {why}")
    sys.exit(1)
print(f"  ✓ all {len(people)} render clean")

if input(f'\nType SEND to email {len(people)} consultants: ').strip() != "SEND":
    sys.exit("Aborted — nothing sent.")

sent = failed = 0
for cid, email, fname in people:
    try:
        deliver(email, fname)
        sent += 1
        print(f"  ✓ [{cid}] {email}")
    except Exception as e:
        failed += 1
        print(f"  ✗ [{cid}] {email}: {e}")

print(f"\ndone — {sent} sent, {failed} failed")
