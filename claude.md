# CLAUDE.md — MyPinkAssistant Project Context

## What This Is
MyPinkAssistant (mypinkassistant.com) is a SaaS CRM and AI assistant for 
Mary Kay consultants. It replaces the discontinued MyCustomers app that 
Mary Kay previously provided. Consultants use it to manage customers, place 
orders via natural language chat, and sync data with Mary Kay's InTouch portal.

## Who Uses It
Independent Mary Kay beauty consultants. Each consultant is a separate tenant.
Data isolation between consultants is critical — every customer, order, and 
job is scoped to a consultant_id. Live in production as of March 2026.

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
- Full order history imported automatically via InTouch Apex/LWC intercept;
  runs nightly and at onboarding
- Personal inventory auto-import: Playwright script (inventory_import.py) pulls
  consultant's personal MK orders into inventory tracking automatically
- Director/team features (REPORT_SYNC): unit member list, Great Start bundle
  tracking, Star Consultant tracking — chat answers any team question via
  text-to-SQL (unit_query intent). Consultant cards with clickable names.

## Pricing & Business Model
- **$5.99/month — all features, no tiers**
- Strategy: undercut competitors (QT Office is $9.99/mo) and capture market
  share fast; technology gap vs competitors is large enough to win on value
- Goal: 5,000 subscribers — Mary Kay has hundreds of thousands of active US
  consultants, TAM is large
- Andrea (Brian's wife, a MK director) is the primary power user and real-world
  test case; her 130-consultant unit is the basis for director feature development

## Competitive Moat
Order history data accumulates over time and powers increasingly smart 
predictions. A competitor can copy the interface and the Playwright scripts,
but cannot replicate months of real order history across hundreds of consultants.
The longer a consultant uses the app, the smarter it gets for them specifically.

## Planned Features (do not build unless explicitly asked)
### Near term
- **Unit member birthdays** — customer birthdays already work ("who has birthdays
  this month" → list with tap-to-text button); same feature for unit_members not
  yet built ("Consultant birthdays this month")
- **Invoices** — both QT Office and Boulevard have this; gap vs competitors
- **Tax report / expense tracking** — high value for consultants filing Schedule C
- **Follow-up reminders** — "remind me to follow up with Jane in 2 weeks"
- **Additional director reports** — more FOReports endpoints (car award, PCP
  participation, recruiting); confirmed API pattern in project_director_apis.md

### Medium term (once order data accumulates)
- **Reorder predictions** — customers overdue based on purchase patterns;
  use_up_rate_months already in catalog CSV for 149 products
- **"What should I do today?"** — AI surfaces top follow-up suggestions
- **Customer value scoring / gone quiet alerts** — top customers by revenue
- **Low inventory alerts** — cross-reference inventory with predicted reorders

### Future / longer term
- Proactive push notifications for reorder reminders
- Tag picker / customer groups in chat
- Text-to-SQL for customer/order data (data_query intent — not just team data)

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
- `app.py` — FastAPI routes, auth, session management, admin panel
- `auth_core.py` — Password hashing, Fernet encryption, consultant CRUD
- `mk_chat_core.py` — AI chat engine: intent HANDLERS only (fetch data, build
  replies, pending flows). Makes no routing decisions (large file)
- `intent_router.py` — ALL message routing: `route()` decides which feature
  answers every chat message, in one documented precedence order. Also holds
  INTENT_REGISTRY (the one place intents are declared) and the routing
  predicates/parsers. Read its module docstring first — it has a plain-English
  overview and a step-by-step recipe for adding a new intent
- `test_intent_golden.py` — intent-routing regression suite harvested from real
  production messages. Run before every deploy that touches routing or chat:
  `python test_intent_golden.py` (or `--no-llm` for the free offline subset)
- `crm_store.py` — Customer/order/unit_member DB queries, fuzzy name search,
  format_consultant_card(), format_customer_card()
- `billing_routes.py` — Stripe checkout, webhooks, portal
- `worker.py` — Background job runner (Playwright automation)
- `worker_queue.py` — Job claiming, locking, retry logic
- `db.py` — DB connection, tx() context manager, is_postgres(), PH placeholder
- `db_setup.py` — All table CREATE statements (SQLite + Postgres compatible)
- `playwright_automation/` — InTouch portal automation scripts
  - `login.py` — InTouch authentication
  - `orders.py` — Order placement ⚠️ FRAGILE — test carefully
  - `new_customer.py` — Customer creation ⚠️ FRAGILE — test carefully
  - `customer_export.py` — Customer list export/sync ⚠️ FRAGILE — test carefully
  - `inventory_import.py` — Personal inventory order import ⚠️ FRAGILE
  - `report_sync.py` — Director/team data sync (unit_members, great_start,
    star_tracking) via Aura intercept + FOReports API
- `run_report_sync.py` — One-shot local test runner for REPORT_SYNC (headed browser)

## How Chat Messages Are Routed (since 2026-07-02)
Every chat message goes through exactly three steps in
`MKChatEngine.handle_message` (mk_chat_core.py):

1. **Route** — `intent_router.route(message, state, catalog)` decides which
   feature answers. It returns an IntentResult with `.intent` (feature name),
   `.slots` (parsed details like product name or quantity), and `.raw_text`
   (the cleaned-up message handlers must use).
2. **Log** — one row goes to intent_logs with that intent name.
3. **Dispatch** — handle_message runs the block matching the intent name.
   Handler blocks only fetch data and build replies; they never decide
   whether they should run.

Rules of thumb:
- Message goes to the WRONG feature → fix intent_router.py (the rule order
  in `route()` is documented at the top of that file).
- RIGHT feature, wrong answer → fix that handler in mk_chat_core.py.
- Adding a new chat feature → follow the "TO ADD A NEW INTENT" recipe in the
  intent_router.py docstring (registry entry → route() rule → dispatch block
  → golden suite case).
- ALWAYS run `python test_intent_golden.py` before deploying routing/chat
  changes. It replays real production phrasings and fails on regressions.
- Mid-conversation flows ("pending" state — order confirms, pickers): route()
  already applies each rule's pending guard, so most rules step aside and let
  the pending flow consume the reply. A few (look book, inventory commands,
  cancel, help) intentionally work even mid-flow.

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
- Our DB mirrors customer, order, and team data but does not replace InTouch
- Customer import runs at account creation automatically
- Historical order data imported automatically via InTouch Apex/LWC intercept;
  runs nightly via Render cron and at onboarding
- Team/unit data synced via REPORT_SYNC job (report_sync.py) using Aura
  intercept + FOReports REST API; requires one Playwright login then plain HTTP

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

## Known Technical Debt (low priority, do not tackle unless asked)
- Consolidate `_row_get()` utility (reimplemented in 3 files)
- Use `tx()` context manager consistently throughout app.py
- Replace `print()` statements with proper logging module
- Split mk_chat_core.py into smaller modules (long-term refactor)

## Conventions & Patterns To Follow

### Before building anything new
**Check if there is an established pattern first.** This codebase has solved
many problems already (DB compat, job queuing, card formatting, intent routing,
fuzzy search, Playwright auth, etc.). Read the relevant existing code before
creating something new — the pattern is almost certainly already there.

### Testing workflow
- **Always test locally (SQLite) before pushing to production (Postgres)**
- Local: `uvicorn app:app --reload` + `python worker.py`
- For Playwright/sync jobs: use the one-shot test runners (e.g. `run_report_sync.py`)
- Only push to Render after local testing passes

### Production debugging & ops
Claude may be asked to help debug production issues, including:
- **Render logs** — checking deploy logs, service logs, or worker output on Render dashboard
- **Jobs table** — querying stuck/failed/stale jobs, investigating retry patterns, clearing bad state
- **Production DB queries** — running read queries against production Postgres to diagnose issues
  (connection info in memory: reference_production_db.md)

**Always confirm with the user before making any changes to production data or manually
modifying job state.** Read-only queries are fine to run; writes require explicit approval.
Deploy workflow: pause job queue → push → wait for Render → unpause queue.

### Code patterns
- All DB queries MUST include `consultant_id` in WHERE clause (tenant isolation)
- New routes need: login check → billing check → then logic (in that order)
- Playwright scripts go in `playwright_automation/`, registered as job types 
  in worker.py
- All new DB tables go in `db_setup.py` — must work for both SQLite and Postgres
- Keep SQLite/Postgres compatibility — use `PH` placeholder (`%s` or `?`) and
  `paramify()` for all new queries; use `tx()` context manager for connections
- Fernet encrypt any third-party credentials before storing
- Never return raw exception messages to the client — log server-side, 
  return generic friendly message
- New features follow chat-first design — if it can't be expressed as a 
  chat prompt, question whether it belongs in the product
- Emergency banner shows on /app (chat) page only — not on login/settings/etc.