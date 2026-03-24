# CLAUDE.md — MyPinkAssistant Project Context

## What This Is
MyPinkAssistant (mypinkassistant.com) is a SaaS CRM and AI assistant for 
Mary Kay consultants. It replaces the discontinued MyCustomers app that 
Mary Kay previously provided. Consultants use it to manage customers, place 
orders via natural language chat, and sync data with Mary Kay's InTouch portal.

## Who Uses It
Independent Mary Kay beauty consultants. Each consultant is a separate tenant.
Data isolation between consultants is critical — every customer, order, and 
job is scoped to a consultant_id. Currently in beta with real consultants,
targeting official launch in ~2 weeks.

## Product Philosophy
**Keep it simple.** The target user is a Mary Kay consultant running a small 
business between appointments, possibly on mobile, possibly via voice-to-text.
One chat box, plain language, done. No dashboards to learn, no buttons to 
click. Every feature should be expressible as a chat prompt.

The original MyCustomers app required navigating menus and clicking through 
screens for every action. MyPinkAssistant collapses all of that into a single 
conversation. That friction reduction is the core value proposition.

## Current Feature Set (what consultants can do today)
- Enter new customers via chat → Playwright auto-creates them in InTouch
- Enter orders in plain language → AI matches products from catalog → 
  Playwright places order on InTouch automatically
- Look up customer info (email, phone, birthday, address) via chat
- Look up last N orders for any customer via chat
- Track personal inventory via chat
- Customer sync: on account creation, existing MyCustomers data is imported 
  automatically so consultants can start entering orders on day one
- Smart customer name matching (fuzzy search) so typos don't break lookups

## Pricing & Business Model
- **Current tier: $5.99/month** — all current features, land grab pricing
- **Planned premium tier: ~$14.99/month** — intelligence features (see roadmap)
- Strategy: get consultants in the system accumulating order history data now,
  build intelligence features on top of that data at the 6 month mark
- Mary Kay has hundreds of thousands of active US consultants — TAM is large

## Competitive Moat
Order history data accumulates over time and powers increasingly smart 
predictions. A competitor can copy the interface and the Playwright scripts,
but cannot replicate months of real order history across hundreds of consultants.
The longer a consultant uses the app, the smarter it gets for them specifically.

## Planned Features (do not build unless explicitly asked)
### Near term (next 60-90 days)
- **Inventory management** — new Playwright script to auto-import consultant 
  orders into personal inventory tracking. Will follow same worker/job queue 
  pattern as existing automation.
- **Birthday reminders** — low hanging fruit, consultants love this, 
  data already stored

### Premium tier unlock (~6 months, once order data accumulates)
- **"What should I do today?"** — AI surfaces top 3-5 follow-up suggestions
  based on order history and reorder patterns. Pull model (consultant asks),
  not push (no notifications yet).
- **Reorder predictions** — identify customers overdue for reorder based on 
  their purchase patterns and product reorder windows
- **Customer value scoring** — top customers by revenue, customers who've 
  gone quiet
- **Low inventory alerts** — cross-reference inventory with predicted reorders
- **Order history summaries** — "what does Jane usually order?" 

### Future / longer term
- Proactive push notifications for reorder reminders
- "What should I do today?" tab/dashboard (only if chat model proves 
  insufficient — keep chat first)

## Tech Stack
- **Backend:** Python, FastAPI
- **Frontend:** Vanilla JS, HTML/CSS (no framework)
- **AI:** OpenAI via mk_chat_core.py (natural language order + CRM interface)
- **Automation:** Playwright (headless browser against InTouch portal)
- **Billing:** Stripe (subscriptions, webhooks)
- **Email:** Resend API
- **Job Queue:** Custom PostgreSQL/SQLite job queue (worker.py + worker_queue.py)
- **Auth:** Session-based (Starlette SessionMiddleware), PBKDF2 password hashing
- **InTouch credentials:** Encrypted at rest with Fernet (MK_ENC_KEY)
- **Worker scaling:** Render supports up to 100 workers, job queue handles 
  concurrent workers correctly with consultant-level locking

## Database Architecture — IMPORTANT
**Local dev:** SQLite (data/mk.db) — fast, zero setup, no install needed
**Production (Render):** PostgreSQL

This dual-DB setup is intentional and should be preserved. The codebase 
handles both via:
- `is_postgres()` checks in db.py
- `PH = "%s" if is_postgres() else "?"` placeholder pattern
- `paramify()` utility in db.py for simple conversions
- `tx()` context manager in db.py for clean connection handling

Do NOT suggest migrating away from SQLite locally — quick local iteration 
matters more than perfect parity.

## Key Files
- `app.py` — FastAPI routes, auth, session management, admin panel (~1300 lines)
- `auth_core.py` — Password hashing, Fernet encryption, consultant CRUD
- `mk_chat_core.py` — AI chat engine, intent routing, CRM operations (~2500 lines)
- `crm_store.py` — Customer/order DB queries, fuzzy name search
- `billing_routes.py` — Stripe checkout, webhooks, portal
- `worker.py` — Background job runner (Playwright automation)
- `worker_queue.py` — Job claiming, locking, retry logic
- `db.py` — DB connection, tx() context manager, utilities
- `playwright_automation/` — InTouch portal automation scripts
  - `login.py` — InTouch authentication
  - `orders.py` — Order placement automation ⚠️ FRAGILE — test carefully
  - `new_customer.py` — Customer creation automation ⚠️ FRAGILE — test carefully
  - `customer_export.py` — Customer list export/sync ⚠️ FRAGILE — test carefully

## ⚠️ Playwright Scripts — Handle With Extreme Care
The Playwright scripts are the most fragile and most valuable part of the 
system. They automate a third-party website (marykayintouch.com) that can 
change without notice. If MK updates their site, scripts may need 
reconfiguring. Failure alerts go to owner via ProjectBroadcast SMS.

Rules when touching Playwright scripts:
- Never refactor without explicit instruction
- Test each change manually before committing
- If InTouch changes their site, use the emergency banner to alert users 
  while fixes are made
- Failure rate is currently near zero — do not break this

## Order Save Timing — Important for Intelligence Features
Orders are saved to mk.db when the job is queued (consultant confirms in 
chat), not when Playwright confirms completion. Reorder intelligence should 
filter on jobs with status='done' to ensure confirmed orders only.

## MyCustomers as Source of Truth
- InTouch/MyCustomers is the official Mary Kay database and source of truth
- Our mk.db mirrors customer and order data but does not replace InTouch
- Customer import runs at account creation automatically
- There is currently NO way to import historical order data from MyCustomers
  (MyCustomers does not export orders) — order history in mk.db only goes 
  back to when the consultant started using MyPinkAssistant

## Environment Variables Required
```
MK_SESSION_SECRET      # FastAPI session signing key
MK_ENC_KEY             # Fernet key for InTouch password encryption
RESEND_API_KEY         # Email sending
MAIL_FROM              # Sender email address
APP_BASE_URL           # e.g. https://mypinkassistant.com
STRIPE_SECRET_KEY      # Stripe API key
STRIPE_PRICE_ID        # Stripe subscription price ID
STRIPE_WEBHOOK_SECRET  # Stripe webhook verification
DATABASE_URL           # PostgreSQL URL (production only, omit for SQLite locally)
MK_ADMIN_EMAILS        # Comma-separated admin email addresses
PB_API_KEY             # ProjectBroadcast API key (worker failure alerts)
PB_CONTACT_ID          # ProjectBroadcast contact for alerts
```

## Local Dev Setup
- Python virtual environment: `venv/` (activate with `source venv/bin/activate`)
- SQLite DB lives at `data/mk.db` (auto-created, gitignored)
- Run app: `uvicorn app:app --reload`
- Run worker: `python worker.py`
- `.env` file holds local secrets (gitignored)

## Current Branch: claude-switch
Working branch for security fixes. Do not merge to main until all fixes 
are tested locally and verified on Render.

### Security Fixes To Complete (in order)
1. **XSS in render_page()** — user-controlled values injected into HTML 
   without escaping. Fix: add `_esc()` helper using `html.escape()` and 
   wrap all user-derived template substitutions.

2. **No rate limiting on /login, /forgot, /onboard** — no brute force 
   protection. Fix: add `slowapi` to requirements, decorate those endpoints.

3. **Exception details leaked to clients** — raw Python exceptions returned 
   in chat and billing responses. Fix: log server-side with logging module, 
   return generic message to client.

4. **requirements-web.txt duplicates** — multiple packages listed twice with 
   conflicting versions (openai, requests, etc). Fix: clean consolidated file.

5. **Order deletion not scoped to consultant_id** — cascading delete in 
   delete_customer_local() uses customer_id only for order deletion.
   Fix: add consultant_id join to the order deletion queries.

### Lower Priority (after launch)
- Consolidate `_row_get()` utility (reimplemented in 3 files — app.py, 
  auth_core.py, crm_store.py)
- Use `tx()` context manager consistently throughout app.py
- Replace `print()` statements with proper logging module
- Split mk_chat_core.py into smaller modules (long-term refactor)

## Conventions & Patterns To Follow
- All DB queries MUST include `consultant_id` in WHERE clause (tenant isolation)
- New routes need: login check → billing check → then logic (in that order)
- Playwright scripts go in `playwright_automation/`, registered as job types 
  in worker.py
- Keep SQLite/Postgres compatibility — use PH placeholder and paramify() 
  for all new queries
- Fernet encrypt any third-party credentials before storing
- Never return raw exception messages to the client — log server-side, 
  return generic friendly message
- Use `_row_get()` for DB row access (works for both sqlite3.Row and 
  psycopg dict_row)
- New features follow chat-first design — if it can't be expressed as a 
  chat prompt, question whether it belongs in the product