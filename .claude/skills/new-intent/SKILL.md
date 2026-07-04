---
name: new-intent
description: Add a new chat intent/feature to MyPinkAssistant the house way — registry entry, route() rule, handler, dispatch, golden cases, suite. Use when Brian asks to add a chat feature, a new phrasing family, or an educate/redirect bubble.
---

# Add a New Intent (the house recipe)

Before anything: read the module docstring of `intent_router.py` — it holds the
canonical "TO ADD A NEW INTENT (recipe)" and the routing precedence overview.
This skill adds the discipline around that recipe. Explain the plan to Brian
BEFORE editing (his standing rule for routing/logic changes).

## The five pieces (all or nothing)

1. **INTENT_REGISTRY entry** (intent_router.py) — name + two flags:
   - `llm_allowed`: may the LLM classifier return this? (keyword/heuristic-only
     intents: False)
   - `interrupts_pending`: may it answer MID-flow (during an order confirm /
     picker)? Ask: "if she's mid-order and says this, should it hijack?" Links
     and help → usually True; educate bubbles and anything starting a new flow
     → False. BOTH layers must agree: the flag AND the `not pending` guard on
     your route() rule.

2. **route() rule** (intent_router.py) — PLACEMENT IS PRECEDENCE: earlier rules
   win. Read the neighboring comments before choosing a spot; add a comment
   citing the incident/request + date. Predicate discipline (learned the hard
   way 2026-07-03):
   - Never claim on a bare substring ("mycustomers" alone hijacked notes/edit
     messages until it required link-ish context). Require the verb/context.
   - Yield to stronger signals: a rule that could swallow real order entries
     must check `_looks_like_new_order_entry` and decline.
   - When unsure, DON'T claim — falling through to unknown/LLM is safer than
     stealing a working message.

3. **Handler** (`mk_chat_core/engine.py`) — `_intent_<name>(self, ctx)` method
   following the neighbors' shape; return None to decline (message falls
   through). Rules:
   - EVERY user-facing string goes in `ui_text.py`, BOTH dicts — never
     hardcoded English. Draft the Spanish and mark it DRAFT-NEEDS-APPROVAL for
     Brian. Command words inside ES strings (skip/cancel/add) stay English —
     the parsers match on them (see the file's header comment).
   - MyCustomers links: `<a href="https://apps.marykayintouch.com/customer-list"
     target="_blank">MyCustomers</a>` — link the mention that says where to GO.
   - Buttons: reuse existing patterns (`.fdp-copy copy-link-btn` for copy
     links, `_QR_*` quick replies). NO inline JS anywhere (CSP) — behavior
     lives in web/app.js.
   - DB access: `PH` placeholder + `tx()`, and every query filtered by
     `consultant_id` (tenant isolation — non-negotiable).

4. **Dispatch entry** — add to `_INTENT_DISPATCH` at the bottom of MKChatEngine.

5. **Golden cases** (test_intent_golden.py) — where they go:
   - keyword-classifier rules → `CASES` with via="kw"
   - route()-level heuristic rules → `ROUTE_CASES` (deterministic, no LLM)
   - "must NEVER be claimed by X" → `NEGATIVE_GUARD_CASES`
   Every new rule needs at least one positive case AND one negative guard for
   the nearest message family it could steal. Anonymize anything harvested
   from real logs (fake names/numbers, keep phrasing shape and typos).

## Verify (in order, all required)

1. Route probes: `intent_router.route(msg, {}, catalog)` for each new phrasing
   + each guard phrasing (and with `{"pending": {...}}` if mid-flow matters).
2. Collateral scan: search recent prod messages (via `mpa_query.py`, last 30
   days, exclude consultant_id 2) for everything the new rule's pattern would
   match — every hit must be currently-broken (improvement) or already routed
   to the same place. Report the count.
3. Local end-to-end: `MKChatEngine().handle_message(msg, 1)` — the ANSWER is
   right, not just the intent.
4. `venv/bin/python test_intent_golden.py --no-llm` then the full run — both
   0 failures.

## Hand-off

Present to Brian: what was added (files + line ranges), the ES drafts awaiting
his approval, the collateral-scan result, suite numbers, and a short list of
phrasings for him to try locally. He tests and pushes on his own schedule —
never commit, never push, never suggest committing.
