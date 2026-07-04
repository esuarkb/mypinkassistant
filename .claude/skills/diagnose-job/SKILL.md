---
name: diagnose-job
description: Diagnose a failed or stuck production job ("job 9142 failed, find where", "why did Cindy's order fail", "orders aren't going through"). Reads the jobs table + step markers, interprets the failure class, checks Render logs if needed, and recommends the next action. Read-only — never requeues or edits jobs.
---

# Diagnose a Failed Job

Answer: WHICH step died, WHY (failure class), and WHAT to do next.
Read-only throughout — requeues/edits are Brian's call; you recommend only.

## Step 1 — The job row (usually sufficient)

```bash
venv/bin/python mpa_query.py - <<'SQL'
SELECT j.id, j.type, j.status, j.attempts,
       j.started_at AT TIME ZONE 'America/Chicago' AS started_cst,
       j.finished_at AT TIME ZONE 'America/Chicago' AS finished_cst,
       c.first_name || ' ' || c.last_name AS consultant, j.consultant_id,
       j.status_msg, j.error
FROM jobs j LEFT JOIN consultants c ON c.id = j.consultant_id
WHERE j.id = <JOB_ID>
SQL
```

No job id given? Find candidates:
`SELECT id, type, status, finished_at, LEFT(error,120) FROM jobs WHERE status='failed' ORDER BY finished_at DESC LIMIT 10`
(add `consultant_id = N` if a name was given — look the id up first).

## Step 2 — Read the step marker

Since 2026-07-04 the error text ends with `[died at <script>/<step_id> (step n/N)]`
— that names the script, step, and usually the exact button/selector.
Map step → code: `grep -rn "<step_id>" playwright_automation/`.
Scripts + step counts: login 8 · orders 17 (+5 orders.cds_address) ·
new_customer 10 (+5 .addr, +4 .subs) · inventory 4 (+4 inventory.login) ·
customer_export 6 · report_sync 11. Optional steps skip numbers — normal.

## Step 3 — Classify (these error semantics are load-bearing)

- **"Timeout: Post-confirm — order was already placed"** or **"Post-save"**:
  the order/customer WENT THROUGH; only the final confirmation wait timed out.
  ⚠️ NEVER recommend re-placing — that double-submits. Verify in MyCustomers.
- **"InTouch: <text>"** prefix: InTouch's own error banner, shown verbatim to
  the consultant (address missing, etc.) — usually a data problem, not a bug.
- **"Customer not found: '<name>'"**: consultant ordered for someone not yet in
  MyCustomers, OR the just-created customer hadn't appeared yet (worker has a
  silent-requeue path for the latter — check `attempts`).
- **"invalid username or password"** / creds-framed errors: check
  `consecutive_login_failures` on the consultant; if SEVERAL consultants are
  failing login at once it's an InTouch outage, not passwords (the outage SMS
  should have fired) → INTOUCH_EMERGENCY.md.
- **Transient net errors** (ERR_ABORTED, net::, ERR_TIMED_OUT): auto-retried
  (login: once; FULL_SYNC: one requeue; timeouts: up to 3 attempts). If
  `attempts` < limit and status is queued again, say "wait — it self-heals".
- **"watchdog: stale job exceeded timeout"**: force-failed after hanging
  (10 min realtime / 90 min FULL_SYNC) — usually a crashed worker; check
  Render events (below) for `server_failed`.
- **Same step failing for MULTIPLE consultants** → MK probably changed that
  page. Run the recon: `venv/bin/python run_ui_recon.py` (read-only, ~2 min,
  diffs all surfaces vs baseline) and follow INTOUCH_EMERGENCY.md.

## Step 4 — Render logs (only if the row didn't settle it)

Key: `RENDER_API_KEY` in .env. Worker service: `srv-d67uepbh46gs73f332pg`
(web: `srv-d67tt1oboq4c73cnnmmg`, scheduler: `crn-d727h00ule4c73dvk6g0`).

```bash
curl -s -G "https://api.render.com/v1/logs" \
  -H "Authorization: Bearer $RENDER_API_KEY" -H "Accept: application/json" \
  --data-urlencode "ownerId=tea-d67tigesb7us73bvop40" \
  --data-urlencode "resource=srv-d67uepbh46gs73f332pg" \
  --data-urlencode "limit=500" \
  --data-urlencode "startTime=<ISO8601 UTC, ~10 min before failure>" \
  --data-urlencode "endTime=<ISO8601 UTC, just after>"
```

Params are `ownerId` + `resource` exactly (not resource[] / serviceId).
Find the traceback, then the LAST `[job N] [script] STEP n/N ...` line above
it — markers print BEFORE actions, so the last marker = the dying step.
Worker crash suspected? `GET /v1/services/<id>/events?limit=20` and look for
`server_failed` (nonZeroExit) — then pull logs for the 10 min before it.
Note: without a time range, limit=500 only reaches back ~15-30 busy minutes.

## Step 5 — Report and recommend

Give Brian: job, consultant, step that died (file:line), failure class, and
ONE recommended action — wait for retry / consultant re-places (NOT for
Post-confirm!) / fix data in MyCustomers / run the named runner script
(run_login_test.py, run_order_test.py, run_new_customer_test.py) / recon +
emergency runbook if MK changed something. If a code fix looks needed in
playwright_automation/, STOP at diagnosis — those files are fragile and fixes
there are explain-first, test-gated work, never casual.
