---
name: weed-garden
description: "Weed the garden" — review production chat logs (intent_logs) for consultant friction, verify each suspected issue against the current code, and present ranked findings with STAGED (never applied) fixes. Use when Brian says "weed the garden", asks for a log review, or asks what consultants are struggling with.
---

# Weed the Garden

Review production intent_logs for consultant pain, verify findings, stage fixes.
**The deliverable is a REPORT. You never edit code during this skill** — not even
"obvious" one-liners. Brian picks what to fix; staged fixes make that fast.

## Hard rules
- Prod reads go through `venv/bin/python mpa_query.py "..."` ONLY (read-only
  runner; see the prod-query skill for schema gotchas).
- **Exclude consultant_id = 2** (Andrea/Brian's own account — internal testing).
- Findings first, Brian decides. Do not change any file. If he approves fixes
  afterwards, that's a separate task using the staged material below.
- Real customer names/phones/emails NEVER go into repo files. Staged golden
  cases must swap in fake names/numbers, keeping the phrasing shape and typos.
- Never suggest committing; never git push.

## Step 1 — Pull the window

Default: yesterday (Brian's timezone, America/Chicago). If he says "last N
days", widen accordingly. Text redacts after 30 days — never query older text.

```bash
venv/bin/python mpa_query.py - <<'SQL'
SELECT created_at AT TIME ZONE 'America/Chicago' AS t_local,
       consultant_id, intent, confidence, message_text, response_text
FROM intent_logs
WHERE created_at >= (CURRENT_DATE - 1)::timestamp AT TIME ZONE 'America/Chicago'
  AND created_at <   CURRENT_DATE::timestamp AT TIME ZONE 'America/Chicago'
  AND consultant_id <> 2
ORDER BY consultant_id, created_at
SQL
```

Also pull a volume-by-intent summary for the window (context for what's normal).

## Step 2 — Read SEQUENCES, not messages

Group by consultant, read each conversation in order. A weird reply usually
makes sense — or clearly doesn't — only next to its neighbors. Judging isolated
messages is the #1 way this review goes wrong.

**Normal, NOT friction (do not report):**
- "yes"/"no"/"1"–"5"/"skip"/"cancel" logged as customer_info or unknown mid-flow
  — the pending layer consumes these correctly.
- Bare product names logging as product_lookup; "show all …" taps never logged.

**Friction signals to hunt:**
- `unknown` on a message that reads like a real request → routing gap.
- Same phrasing shape → DIFFERENT intents on different occasions → LLM
  coin-flip; needs a deterministic keyword rule (worst kind — find these).
- Same message typed twice in a row → first answer didn't help.
- `cancel` after a multi-message struggle; repeated rephrasing.
- A picker ("reply 1-3") when the message clearly named ONE person/product →
  extraction problem in the handler, not routing.
- Generic dead-ends: "No close matches", "I couldn't find …", word-salad
  replies ("I couldn't find *the was* in your saved customers").
- Typos fuzzy matching should have caught.

## Step 3 — VERIFY before you report (mandatory)

For every suspected issue, replay it against the CURRENT code — many log
entries predate fixes and are already dead:

```python
# offline routing probe (no LLM cost):
import intent_router
from intent_router import IntentResult
intent_router.parse_intent_with_openai = lambda m, s=None: IntentResult("<fell-to-llm>", 0.0, raw_text=m)
print(intent_router.parse_intent("the exact message").intent)

# full pipeline (heuristic rules need the catalog):
from mk_chat_core import load_catalog, get_catalog_path_for_language
catalog = load_catalog(get_catalog_path_for_language("en"))
print(intent_router.route("the exact message", {"pending": None}, catalog).intent)
```

Report an issue ONLY if it still reproduces. List already-fixed items in one
line each under "confirmed fixed" (useful signal, zero action). When a finding
blames specific code, cite file:line you actually read — never from memory.
Check KNOWN_BUGS in test_intent_golden.py and the future-features backlog
first: some "gaps" are deliberate non-features (e.g. bulk SMS) — say so
instead of proposing them.

## Step 4 — Judge by INTENT, not phrasing (accommodate / educate / ignore)

MPA is a focused tool, not a general chatbot. The goal is NEVER to absorb
every random thing consultants type — it's to make the things the product
does well work when asked naturally. For every verified friction episode,
answer first: **what was this consultant trying to ACCOMPLISH, and is that a
supported feature?**

- **Supported feature, natural phrasing** (how most consultants would say it)
  → candidate fix.
- **Supported feature, one person's odd phrasing** → watch-list, not a fix.
- **Consultant doesn't know a capability exists** (doing manually what MPA
  already does, e.g. pasting inventory the auto-import already covers) →
  EDUCATE finding: stage help-bubble/copy, not a routing rule.
- **Not a feature and not on the backlog** → deliberate non-feature: say so;
  educate toward the nearest supported path if one exists, otherwise ignore.

**One-off threshold — a finding qualifies for a staged fix only if** ≥2
distinct consultants hit it, OR one consultant fought it repeatedly
(retries/cancels/abandonment), OR it's structurally certain to recur (a
designed funnel or deterministic rule guarantees future traffic). Everything
else is a watch-list item, not a finding.

**Watch-list — `data/weed_garden/WATCHLIST.md`** (local-only, like reports).
One line per item: date first seen, consultant, phrasing shape, what happened.
Every run: read it BEFORE analyzing the window, check for recurrences, promote
anything that recurred (it now meets the threshold), prune items 30+ days
stale. One-offs don't evaporate with the daily report — recurrence is the
promotion signal.

**Fix hierarchy (educate before accommodate).** When staging, prefer in order:
1. **Educate** — point at an existing capability via the help-bubble system
   (`_HELP_TOPICS` / `*_help` intents) or a copy tweak. Cheapest, zero
   routing risk, and it compounds: the consultant learns the tool.
2. **Fix extraction/handling of natural phrasing** for a core action the tool
   already claims to do (the "Remove one dark brunette" class).
3. **New routing rule** — last resort, only for a phrasing family multiple
   consultants use. Never a rule whose only job is absorbing one person's
   typing style.

## Step 5 — The report

Rank by **distinct consultants affected** (4 consultants × 1 hit beats
1 consultant × 10 retries), then frequency. For each finding:

- One-line title + friction class (routing gap / LLM coin-flip / handler
  extraction / copy dead-end / educate gap / feature gap / deliberate
  non-feature)
- The Step-4 intent call: what the consultant was trying to accomplish, and
  why this is a fix vs educate vs watch-list item
- Verbatim examples (log text is fine in the REPORT — it's local-only)
- What the consultant expected vs got
- Verified-current: yes (replayed) — with the replay result

Then the **STAGED FIXES** section for each finding worth fixing:

- **Proposed change**: exact file + the old/new snippet it would take
  (drafted, not applied). Wrong feature answered → intent_router.py; right
  feature, wrong answer → that handler in mk_chat_core/.
- **Golden cases**: the CASES/ROUTE_CASES lines to add (anonymized), including
  NEGATIVE guards proving the rule steals nothing.
- **Collateral scan plan**: what pattern to scan historical messages for to
  prove no theft.
- **Risk tag**: copy-only / routing / handler / touches-fragile (anything in
  playwright_automation/ or order_parse.py discount code = flag-only, extra
  care, never in a casual fix batch).
- **Effort**: minutes/hours.

Include a **Watch-list** section: new one-offs added this run, recurrence
checks on existing items (promoted / still quiet / pruned). Update
`data/weed_garden/WATCHLIST.md` to match.

Save the full report to `data/weed_garden/YYYY-MM-DD.md` (data/ is gitignored)
AND give Brian the ranked summary in chat — findings table + one recommendation
line. STOP THERE.

## Step 6 — If Brian approves fixes (separate task, after his reply)

Follow the staged material plus the 6-step template: probe → find extent →
rule (placement matters — read neighboring comments; cite the incident + date
in a comment) → check the handler answers right, not just routes right
(`MKChatEngine().handle_message(msg, 1)` locally) → pin golden cases → run the
collateral scan and `python test_intent_golden.py` (full, must exit 0).
Then hand back to Brian — he tests locally and pushes himself.
