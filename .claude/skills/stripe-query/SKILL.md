---
name: stripe-query
description: Answer Stripe/billing questions (active subscribers, MRR, trials, failed payments, dunning/retries, renewals, refunds, a customer's subscription state) with read-only Stripe API calls. Use for "why did active drop", "who failed payment", "renewals this week", "did X's trial convert".
---

# Stripe queries (read-only)

The `stripe` python lib is in the venv; the key is in `.env` as
`STRIPE_SECRET_KEY` — **it is the LIVE key.**

## Hard rules
- READ-ONLY: only `.list()`, `.retrieve()`, `.search()`. Any write — cancel,
  refund, credit, void invoice, update subscription — is Brian-only, done with
  his explicit approval in that message, never as part of answering a question.
- Never print full API keys, client_secrets, or payment-method numbers.
- Cross-check MPA when relevant: `consultants.billing_status` mirrors Stripe
  via webhooks (query via mpa_query.py / the prod-query skill).

## The boilerplate that actually works

```python
# ALWAYS pass the explicit path — bare load_dotenv() CRASHES in heredocs
# (find_dotenv AssertionError, learned 2026-07-05)
from dotenv import load_dotenv
load_dotenv("/Users/desktop/Documents/Brian's Folder/Python Projects/MK Automation/.env")
import os, stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
```

Run with `venv/bin/python` from the project dir. For >100 records use
`stripe.Subscription.list(limit=100, status="all").auto_paging_iter()`.

## Status semantics (the part other sessions get wrong)

- Statuses: `trialing → active → past_due → canceled/unpaid` (+ incomplete*).
- **"Active subscribers" counts status=active ONLY.** A single failed renewal
  charge instantly moves a sub to `past_due` → Active drops by 1 even though
  nobody canceled. A successful auto-retry moves it back → count recovers.
- **MRR keeps counting past_due** subs until actual cancellation — so Active
  can dip while MRR holds.
- Trials are NOT in Active; each converts (+1 Active) when its trial-end
  invoice pays.
- Dunning state lives on the invoice: `inv = stripe.Invoice.retrieve(
  sub.latest_invoice)` → `inv.attempt_count`, `inv.next_payment_attempt`
  (epoch; None = no more retries scheduled).
- **MPA access gate allows `past_due`** (billing_routes.py ~679: active/
  trialing/past_due) — consultants keep the app during dunning; they lose it
  only on full cancellation. Don't tell Brian someone "lost access" unless
  status is actually canceled/unpaid.

## Field gotchas

- **`current_period_end` lives on `sub["items"]["data"][0]`, NOT the top-level
  subscription** (returns null there — API version quirk). Same for the price:
  `items.data[0].price.unit_amount` (cents).
- Timestamps are epoch UTC — convert to Central for Brian and say so.
- `expand=["data.customer"]` on list calls saves N+1 retrieves.

## Known operational gotchas (from live incidents)

- **Manual cancellations leave OPEN invoices** that keep charging the card
  (June 2026: three consultants, voided by hand). After any manual cancel,
  check `stripe.Invoice.list(customer=..., status="open")` — voiding is a
  WRITE → Brian does it / approves it.
- Referral rewards = negative `Customer.create_balance_transaction` credits
  (one $5.99/referee, webhook-driven, `referrals.rewarded_at` in prod DB
  marks paid ones). A "weird" $0 invoice is usually a credit consuming it.
- Trials come from the referral flow (30-day) — a `trialing` sub with
  `referred_by_consultant_id` set in the DB is normal.

## Worked example — status counts + dunning detail

```python
from collections import Counter
counts = Counter(); past_due = []
for sub in stripe.Subscription.list(limit=100, status="all").auto_paging_iter():
    counts[sub.status] += 1
    if sub.status == "past_due":
        cust = stripe.Customer.retrieve(sub.customer)
        inv = stripe.Invoice.retrieve(sub.latest_invoice)
        past_due.append((cust.email, inv.attempt_count, inv.next_payment_attempt))
```

## Worked example — renewals in the next N days

```python
import datetime
now = datetime.datetime.now().timestamp(); horizon = now + 7*86400
for s in stripe.Subscription.list(status="active", limit=100,
                                  expand=["data.customer"]).auto_paging_iter():
    item = s["items"]["data"][0]
    cpe = item.get("current_period_end")          # item level — see gotchas
    if cpe and now <= cpe <= horizon:
        print(s["customer"].get("email"), cpe, item["price"]["unit_amount"]/100)
```

## Output style

Answer the actual question in one plain sentence after the data, convert
money to dollars, and reconcile with what Brian sees in the Stripe app
("Active dropped because X went past_due; retry scheduled Tuesday").
