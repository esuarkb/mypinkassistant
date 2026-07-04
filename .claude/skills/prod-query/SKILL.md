---
name: prod-query
description: Answer questions about production data (consultants, jobs, orders, chat logs, subscriptions) by running read-only SQL against the prod Postgres through mpa_query.py. Use for "how many...", "show me...", "when did...", "which consultants..." questions about live data.
---

# Production data queries (read-only)

Answer the user's question by writing a SELECT and running it through the
safe runner — **never** with raw psycopg2, and **never** by putting the
DATABASE_URL in an ad-hoc script:

```bash
cd "/Users/desktop/Documents/Brian's Folder/Python Projects/MK Automation"
venv/bin/python mpa_query.py "SELECT ..."
venv/bin/python mpa_query.py - <<'SQL'      # long queries via stdin
SELECT ...
SQL
```

The runner is physically read-only (server-enforced), caps at 500 rows,
30s timeout. If it refuses something, do NOT work around it — the refusal
is the point. Production WRITES are out of scope for this skill entirely:
they require Brian's explicit approval and are done separately.

## Schema cheat-sheet (the gotchas that bite)

- **jobs**: columns are `type` (NOT job_type), `status`
  ('queued'/'running'/'done'/'failed'), `created_at`, `claimed_at`,
  `started_at`, `finished_at` (NO updated_at), `error` (owner-facing, has
  "[died at script/step]" markers), `status_msg` (consultant-facing),
  `payload_json`, `consultant_id`, `attempts`, `admin_hidden`.
  Job types: NEW_ORDER_ROW (one per ITEM, not per order), NEW_CUSTOMER,
  FULL_SYNC (nightly), REPORT_SYNC, PCP_SYNC, INITIAL_SYNC, IMPORT_*.
- **consultants**: COUNT(*) is NOT the subscriber count — it includes
  canceled/never-subscribed. Subscribers = `billing_status = 'active'`,
  trials = `'trialing'`. Also has: language, referred_by_consultant_id,
  consecutive_login_failures, initial_sync_completed.
- **intent_logs**: message_text/response_text are REDACTED after 30 days —
  always filter `created_at::timestamp > now() - interval '30 days'` when
  reading text. Columns: consultant_id, intent, confidence, message_text,
  response_text, user_agent, created_at.
- **customers**: tenant-scoped by consultant_id (always filter on it for
  per-consultant questions). Beware `source_status` when counting "real"
  customers (imported vs active — check reference_data_query_rules memory).
- **orders / order_items**: order_id on jobs is NULL until the overnight
  sync links it. Orders' `source`: intouch_import / cds / (MPA-placed).
  Counting orders ≠ counting NEW_ORDER_ROW jobs (multi-item quirk).
- **unit_members / unit_great_start / unit_star_tracking / unit_rise_radiate /
  unit_registrations**: director team data, refreshed by nightly report sync.
- **referrals**: referrer/referee consultant ids, rewarded_at NULL until paid.
- **system_settings**: key/value ops flags (queue_paused, worker_max,
  worker_max_nightly, ui_emergency_*).
- All timestamps are UTC. Brian is US Central (CST/CDT) — convert when he
  asks about "yesterday" or clock times, and say which timezone you used.

## Output

Show the result, then answer the user's actual question in one plain
sentence — don't make them read the table. Note truncation if the 500-row
cap hit. For anything that looks alarming (mass failures, zero rows where
data should exist), say so explicitly rather than just reporting numbers.
