# InTouch Emergency Runbook

**Use this when:** consultants say orders aren't going through, the alert phone gets
🚨 texts, or MyPinkAssistant jobs are failing — and especially if Brian isn't
available. Written so Andrea (or an AI session) can act without touching code.

(For a lost/corrupted database, use `RESTORE.md` instead — that's a different emergency.)

---

## 1. Figure out which problem it is (5 minutes)

| What you see | What it means | What to do |
|---|---|---|
| ONE consultant failing, everyone else fine | Her InTouch password is wrong | Nothing — she gets an automatic email telling her to fix it in Settings |
| 🚨 SMS: "InTouch outage detected — multiple consultants failing login" | The system already diagnosed it: InTouch itself is down or changed | Go to step 2 |
| Several consultants failing, no SMS yet | Same as above, detection just hasn't tripped | Go to step 2 |
| Jobs fail AFTER login works (SMS says e.g. "died at orders/add_to_bag") | Mary Kay changed a page — MPA needs a code fix | Step 2, then step 3 |

**Quick test that settles it:** open marykayintouch.com in a normal browser and log in
with Andrea's account. Can't log in → Mary Kay is having an outage; it will pass, and
MPA retries safely. CAN log in but MPA jobs still fail → Mary Kay changed their site
and MPA needs a fix (step 3).

**Known quirk:** affected consultants see "update your InTouch credentials in
Settings" even when the real problem is InTouch itself — they didn't do anything
wrong, and their passwords are fine. Reassure them; the banner (below) is how.

## 2. Immediate response — all from the admin page, no code

Log in at **mypinkassistant.com/admin** (any admin-listed email works).

1. **Turn on the emergency banner.** Check "Enable emergency banner", type a message,
   click Save Banner. It appears on every consultant's chat page instantly. Suggested:
   > "Mary Kay's InTouch site is having issues, so new orders and customer entries are
   > delayed. Everything you enter is saved and will process automatically once InTouch
   > is back. Lookups, followups, and inventory all still work. — MyPinkAssistant"
2. **Decide about the queue (same page, "Pause Queue"):**
   - InTouch outage (their side): **leave the queue running.** Retries are safe and
     everything processes itself when they recover.
   - Mary Kay CHANGED the site (login works, jobs still die): **pause the queue** so
     jobs stop failing over and over. They wait safely as "queued" until the fix.
3. **What still works during any of this** (most of the product): customer lookups,
   order history, followups, birthdays, inventory, team/director reports, product
   lookups. Only NEW orders/customers going INTO InTouch and the nightly refresh are
   affected.

## 3. Getting it fixed (when it's a site change, not an outage)

- The failed job's error now names the exact broken step, e.g.
  `[died at orders/add_to_bag (step 11/17)]` — visible on /admin under "Recent failed"
  and in the alert SMS.
- **If Brian is available:** he takes it from here (diagnostic runners:
  `run_login_test.py`, `run_order_test.py`, `run_new_customer_test.py`).
- **If Brian is NOT available (Andrea + Claude can do this):** open Claude Code on the
  iMac in this project folder and say: *"InTouch changed something and orders are
  failing — the job error says [paste it]. Diagnose and propose a fix."* Claude has a
  saved runbook for exactly this. It will explain the fix before touching anything,
  then ask you to test — usually by running a test script that opens a visible browser
  and places a practice order while you watch. It should behave exactly like a normal
  order.
- **Deploying the fix — you never touch git; you just tell Claude.** Only after a
  passing test:
  1. On /admin, click **Pause Queue**.
  2. Tell Claude: **"The test passed — push the fix now."** (Claude will not push
     unless you say it explicitly, so use those words.)
  3. When Claude confirms the push, wait ~5 minutes for Render to deploy, then click
     **Unpause Queue** on /admin.
  Never ask for a push if you didn't run the test or it didn't pass — a bad push makes
  things worse than a paused queue ever will.

## 4. Recovery once InTouch is back / the fix is deployed

1. /admin → unpause the queue (if paused). Queued jobs process within seconds.
2. Orders that failed during the window: the consultant saw a "something went wrong —
   please try again" style message, and the default answer is exactly that — **re-place
   the order in chat**. Jobs still sitting "queued" (never ran) need nothing; they
   process on unpause. Brian's practice for stragglers: on /admin "Recent failed",
   check whether the consultant already retried (a newer matching order exists) — only
   consider requeuing an old failed order if she clearly hasn't noticed anything went
   wrong, so she doesn't end up with a duplicate.
3. Update the banner ("All fixed — failed orders can be re-entered...") for a day,
   then turn it off.
4. That night, confirm the nightly sync ran clean (jobs table: FULL_SYNC all "done").

## 5. Access needed to operate MPA in Brian's absence

**Andrea needs no written-down secrets for anything in this runbook:**
- **Her MPA admin login** (her email is on the admin list) → the /admin page: banner,
  queue pause, failed-jobs view.
- **Her own InTouch login** (memorized) → the "can I log into InTouch?" triage test.
- **The iMac** → Claude Code in this project folder, any time. The machine's git and
  config are already set up, which is why Claude can diagnose, run tests, and push
  when explicitly told to — no GitHub/Render passwords needed for the emergency path.
- **The alert phone** (🚨 SMS texts) and the **support@mypinkassistant.com** mailbox
  (login-failure + watchdog emails) are where the system reports problems.

Brian-only accounts, NOT needed for this runbook: Render dashboard, Stripe, Resend,
ProjectBroadcast, GitHub website login.

⚠️ **MK_ENC_KEY** (in `.env` and Render env vars) is irreplaceable — if lost, every
consultant's stored InTouch password becomes undecryptable and all of them would have
to re-enter credentials. Never rotate/delete it casually. (Details in RESTORE.md.)

## Known gaps (accepted for now — candidates for future work)

- **No kill switch:** there's no one-click way to disable only the InTouch-writing
  features while keeping everything else; the queue pause is all-or-nothing.
- **Nightly sync can silently no-op:** if InTouch changes the order-history/customer
  pages, the nightly sync can import nothing and still show "done" ✅ — only the
  team-report portion alerts on failure. Stale-looking order history is the symptom.
- **Misleading credentials warning** during outages (see Known quirk, step 1).
