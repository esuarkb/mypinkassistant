"""Golden intent-routing regression suite.

Cases harvested from real production intent_logs on 2026-07-02 (3,832 messages,
1,810 distinct phrasings reviewed) and anonymized — all names/addresses/phones/
emails below are fake, but the phrasing patterns (including typos) are real.

Run before every deploy:
    python test_intent_golden.py            # full run — includes OpenAI fallback cases (~$0.01)
    python test_intent_golden.py --no-llm   # keyword layer only: offline, free, deterministic

How cases work:
  via="kw"  — must be answered by the keyword fast-path in intent_router.py.
              If one of these falls through to the OpenAI fallback, that is a
              FAILURE even if the LLM guesses right (it means a keyword rule
              regressed and we're now paying latency + tokens for it).
  via="llm" — expected to fall through to the OpenAI fallback. Skipped with --no-llm.
  expected  — a single intent, or a tuple of acceptable intents for genuinely
              ambiguous phrasings the LLM classifies inconsistently.

KNOWN_BUGS at the bottom: real misroutes observed in production, verified against
the router. They do NOT fail the suite while still broken; the suite tells you
when one gets FIXED (move it up into CASES) or when its behavior CHANGES to some
third intent (that fails — it means a fix attempt went sideways).

Refresh guidance: intent_logs message text is redacted after 30 days once the
retention change deploys — harvest new phrasings into this file periodically
(see memory: project_weed_the_garden).
"""
import sys
from intent_router import IntentResult

# ---------------------------------------------------------------------------
# CASES: (message, expected_intent(s), via)
# ---------------------------------------------------------------------------
CASES = [
    # --- cancel (kw) ---
    ("cancel",                                  "cancel",            "kw"),
    ("stop",                                    "cancel",            "kw"),
    ("nevermind",                               "cancel",            "kw"),
    ("start over",                              "cancel",            "kw"),

    # --- chat_help (kw) ---
    ("help",                                    "chat_help",         "kw"),
    ("what can you do",                         "chat_help",         "kw"),

    # --- app_help (kw) ---
    ("app",                                     "app_help",          "kw"),
    ("how do i add the app to my home screen",  "app_help",          "kw"),
    ("install the app on my ipad",              "app_help",          "kw"),

    # --- mid-flow reply tokens must NOT call the LLM ---
    # "yes"/"no" hit the bare-name rule → customer_info (logged 1,360x in prod).
    # Harmless by contract: the customer_info handler in mk_chat_core is guarded
    # by `if not pending`, so mid-flow replies fall through to the pending flow.
    # Pinned here so a router change that starts LLM-calling these gets caught.
    ("yes",                                     "customer_info",     "kw"),
    ("no",                                      "customer_info",     "kw"),
    ("3",                                       "unknown",           "kw"),

    # --- inventory (kw — the word "inventory" routes directly) ---
    ("show my inventory",                       "inventory",         "kw"),
    ("my inventory list",                       "inventory",         "kw"),
    ("add 2 repair sets to inventory",          "inventory",         "kw"),
    ("remove 2 repair sets from inventory",     "inventory",         "kw"),
    ("add one lifting serum to my inventory",   "inventory",         "kw"),

    # --- unit_query (kw) ---
    ("i3",                                      "unit_query",        "kw"),
    ("t6",                                      "unit_query",        "kw"),
    ("who is i3",                               "unit_query",        "kw"),
    ("my team",                                 "unit_query",        "kw"),
    ("who is inactive",                         "unit_query",        "kw"),
    ("who has myshop",                          "unit_query",        "kw"),
    ("who is registered for seminar",           "unit_query",        "kw"),
    ("who is close to a great start bundle",    "unit_query",        "kw"),
    ("what is everyone's star consultant status", "unit_query",      "kw"),
    ("team member linda vale",                  "unit_query",        "kw"),
    ("who made ruby this month",                "unit_query",        "kw"),
    ("who is on track for star",                "unit_query",        "kw"),
    ("which consultants have ordered this month", "unit_query",      "kw"),
    ("new consultants this month",              "unit_query",        "kw"),
    ("phone numbers of my team members",        "unit_query",        "kw"),
    # plural "birthdays" misses the keyword rules → LLM decides; both routes
    # have working handlers (customer_info birthday lookup / data_query SQL)
    ("any consultant birthdays this month",     ("unit_query", "customer_info", "data_query"), "llm"),

    # --- car_program (kw) ---
    ("car program",                             "car_program",       "kw"),
    ("car production",                          "car_program",       "kw"),
    ("last quarter car production",             "car_program",       "kw"),
    ("what's my car program status",            "car_program",       "kw"),
    ("career car update",                       "car_program",       "kw"),
    ("who can earn a car",                      "car_program",       "kw"),

    # --- leaderboard ---
    ("top 5 customers",                         "leaderboard",       "kw"),
    ("pcp list",                                "leaderboard",       "kw"),
    ("show my vip customers",                   "leaderboard",       "kw"),
    ("who spent the most",                      "leaderboard",       "kw"),
    ("who are my best customers",               "leaderboard",       "llm"),

    # --- top_sellers (kw) ---
    ("what are my top selling products",        "top_sellers",       "kw"),
    ("top selling items this quarter",          "top_sellers",       "kw"),
    ("best sellers this year",                  "top_sellers",       "kw"),
    ("what's my top seller",                    "top_sellers",       "kw"),

    # --- lapsed_customers (kw) ---
    ("who hasn't ordered in 6 months",          "lapsed_customers",  "kw"),
    ("show all lapsed 90 days",                 "lapsed_customers",  "kw"),
    ("haven't ordered since dec",               "lapsed_customers",  "kw"),
    ("which customers have gone quiet",         "lapsed_customers",  "kw"),

    # --- data_query (kw) ---
    # NOTE: "who ordered last month" routes to unit_query since the 6/18-6/29
    # trigger additions ("ordered last month" is a unit trigger). Ambiguous for
    # non-directors (they likely mean customers) — revisit in routing consolidation.
    ("who ordered last month",                  "unit_query",        "kw"),
    ("who has ordered only once",               "data_query",        "kw"),
    ("how many customers do i have",            "data_query",        "kw"),
    ("who buys timewise",                       "data_query",        "kw"),
    ("what's my total sales this year",         "data_query",        "kw"),
    ("orders in may",                           "data_query",        "kw"),
    ("customers who never ordered",             "data_query",        "kw"),
    ("online orders this week",                 "data_query",        "kw"),
    ("total revenue last month",                "data_query",        "kw"),
    ("who ordered the timewise set",            "data_query",        "kw"),
    # --- data_query (llm) ---
    ("which customers order beige foundation",  "data_query",        "llm"),
    ("how much have i sold this month",         "data_query",        "llm"),
    ("which of my customers use the clearproof set", "data_query",   "llm"),

    # --- customers_by_city (kw) ---
    ("customers in ogden",                      "customers_by_city", "kw"),
    ("who are my customers in huntsville",      "customers_by_city", "kw"),
    ("which of my customers live in ogden, ut", "customers_by_city", "kw"),
    ("all my customers that live in sheboygan", "customers_by_city", "kw"),
    ("springfield customers",                   "customers_by_city", "kw"),

    # --- customer_spend (kw) ---
    ("how much has jane spent",                 "customer_spend",    "kw"),
    ("how much did martha spend this year",     "customer_spend",    "kw"),
    ("what is karen's total spent",             "customer_spend",    "kw"),

    # --- edit_request (kw) ---
    ("update jane smith's address 123 maple st springfield il 62704", "edit_request", "kw"),
    ("can you change kelly's last name spelling", "edit_request",    "kw"),
    ("add this address to dora blake 204 water street", "edit_request", "kw"),
    ("fix sarah's email",                       "edit_request",      "kw"),
    ("add phone (555) 779-0000",                "edit_request",      "kw"),

    # --- customer_info (kw) ---
    ("jane doe",                                "customer_info",     "kw"),
    ("carol",                                   "customer_info",     "kw"),
    ("what is jane's address",                  "customer_info",     "kw"),
    ("what is jane's phone number",             "customer_info",     "kw"),
    ("whats danielles address",                 "customer_info",     "kw"),
    ("jane smith info",                         "customer_info",     "kw"),
    ("paula west address",                      "customer_info",     "kw"),
    ("email for jane doe",                      "customer_info",     "kw"),
    ("who has a birthday in july?",             "customer_info",     "kw"),
    ("show customer marion vale",               "customer_info",     "kw"),
    ("is there another address for lorrie ray", "customer_info",     "kw"),

    # --- recent_orders (kw) ---
    ("last order for kimberly moss",            "recent_orders",     "kw"),
    ("jane's orders",                           "recent_orders",     "kw"),
    ("show all of jane's orders",               "recent_orders",     "kw"),
    ("what did jane order in jan 2024",         "recent_orders",     "kw"),
    ("amber cole recent order",                 "recent_orders",     "kw"),
    ("show me her last order",                  "recent_orders",     "kw"),
    ("order history for jane",                  "recent_orders",     "kw"),
    ("last 5 orders for beckie moss",           "recent_orders",     "kw"),
    # NOTE: "X ordered 2 sets" is order ENTRY; parse_intent returns recent_orders
    # by design and mk_chat_core overrides to new_order via _looks_like_new_order_entry.
    # This case pins the parse_intent half of that contract.
    ("jane ordered 2 timewise sets",            "recent_orders",     "kw"),
    # --- recent_orders (llm) ---
    ("what has jane bought",                    "recent_orders",     "llm"),
    ("when did leann price last purchase?",     "recent_orders",     "llm"),

    # --- new_order (kw) ---
    ("order for michelle ward",                 "new_order",         "kw"),
    # was misrouted to edit_request until 2026-07-02 ("set" in product names
    # matched the edit-verb regex); new_order now checks first
    ("order for gwen hart, timewise repair set", "new_order",        "kw"),
    ("new order for jane doe charcoal mask",    "new_order",         "kw"),
    ("add an order for peggy for blush stick and lip liner", "new_order", "kw"),
    ("please add an order for jennifer moss",   "new_order",         "kw"),
    ("place order for sarah smith",             "new_order",         "kw"),
    # --- new_order (llm) ---
    ("create new cds order",                    "new_order",         "llm"),
    ("trisha allen new order will free makeup remover, black, ultimate mascara", "new_order", "llm"),
    ("sarah needs a timewise set and cleanser", "new_order",         "llm"),

    # --- new_customer ---
    ("create jennifer roberts",                 "new_customer",      "kw"),
    ("add new customer",                        "new_customer",      "llm"),
    ("new customer jane smith",                 "new_customer",      "llm"),
    ("new customer: sylvia hart 2885 w iliff ave springfield il 62704 shart@example.com", "new_customer", "llm"),
    ("new customer trisha allen, 1533 parrish court, owensboro ky 42301", "new_customer", "llm"),
    # was misrouted to app_help until 2026-07-02 (bare "phone" in _app_context)
    ("new customer jane smith, phone number 555-572-0000, email jane@example.com", "new_customer", "llm"),

    # --- product_lookup ---
    ("what are the ingredients in the eye renewal cream", "product_lookup", "kw"),
    ("ingredients in charcoal mask",            "product_lookup",    "kw"),
    ("how much is the lifting serum",           "product_lookup",    "llm"),
    ("price of the charcoal mask",              "product_lookup",    "llm"),

    # --- order_add (llm only — no keyword rule; mid-order these are usually
    #     caught by the pending flow before intent matters). Bare "add X" with
    #     no conversation context is genuinely ambiguous — see CONTEXT_CASES. ---
    ("now add a translucent powder",            "order_add",         "llm"),

    # --- order_remove (llm only) ---
    ("remove ultimate mascara",                 "order_remove",      "llm"),
    ("remove 2 honey and luster",               "order_remove",      "llm"),
    ("remove one makeup remover",               "order_remove",      "llm"),
]

# Cases that depend on conversation state — in production these arrive
# mid-conversation and parse_intent_with_openai sees the last referenced
# customer, which is what tips "add X" to order_add (logged 3x each in prod).
# (message, state_dict, expected_intent(s), via)
CONTEXT_CASES = [
    ("add spf 50",           {"last_ref_customer_name": "Jane Doe"}, "order_add", "llm"),
    ("add replenishing serum", {"last_ref_customer_name": "Jane Doe"}, "order_add", "llm"),
]

# Deterministic slot checks for keyword rules that extract slots.
# (message, slot_name, expected_value)
SLOT_CASES = [
    ("customers in ogden",            "city",      "Ogden"),
    ("springfield customers",         "city",      "Springfield"),
    ("top selling items this quarter", "timeframe", "quarter"),
    ("best sellers this year",        "timeframe", "year"),
]

# ---------------------------------------------------------------------------
# KNOWN_BUGS: (message, correct_intent, currently_returns, note)
# For real production misroutes you can't fix immediately. Suite passes while
# they stay broken; flags them loudly when fixed (move to CASES) or if behavior
# changes to some third intent (fails).
#
# History: the original five entries (bare "phone" → app_help; "order for X,
# ...set" → edit_request) were fixed in intent_router.py on 2026-07-02 and
# graduated into CASES above.
# ---------------------------------------------------------------------------
KNOWN_BUGS = []

# ---------------------------------------------------------------------------
# FUTURE_CORE_CASES — routed correctly today by pre-intent heuristics inside
# mk_chat_core.handle_message, NOT by intent_router.parse_intent (which returns
# something else or falls to the LLM). Not runnable against parse_intent yet.
# Enable these when routing is consolidated into intent_router (planned step 2).
# ---------------------------------------------------------------------------
FUTURE_CORE_CASES = [
    ("charcoal mask",                          "product_lookup",  "exact catalog match early-exit"),
    ("lifting serum",                          "product_lookup",  "exact catalog match early-exit"),
    ("how many timewise sets do i have on hand", "inventory",     "_looks_like_inventory_count early-exit"),
    ("spanish look book",                      "look_book",       "look book early-exit"),
    ("what should i order",                    "inventory",       "_looks_like_low_stock_query early-exit"),
]


def main():
    run_llm = "--no-llm" not in sys.argv

    import intent_router
    real_fallback = intent_router.parse_intent_with_openai
    used_fallback = {"flag": False}

    def tracking_fallback(message, state=None):
        used_fallback["flag"] = True
        if not run_llm:
            return IntentResult(intent="<llm-skipped>", confidence=0.0, raw_text=message)
        return real_fallback(message, state)

    intent_router.parse_intent_with_openai = tracking_fallback

    W = 58
    passed = failed = skipped = 0
    failures = []

    print(f"{'Message':<{W}} {'Expected':<18} {'Got':<18} Path  OK?")
    print("-" * (W + 50))

    for msg, expected, via in CASES:
        if via == "llm" and not run_llm:
            skipped += 1
            continue
        accepted = expected if isinstance(expected, tuple) else (expected,)
        used_fallback["flag"] = False
        r = intent_router.parse_intent(msg)
        path = "llm" if used_fallback["flag"] else "kw"
        ok = r.intent in accepted
        if not ok and path == "llm" and run_llm:
            r = intent_router.parse_intent(msg)  # LLM answers can flake; one retry
            ok = r.intent in accepted
        if ok and via == "kw" and path == "llm":
            ok = False  # keyword rule regressed — now burning an LLM call
        mark = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((msg, "/".join(accepted), r.intent, f"{via}->{path}"))
        print(f"{msg[:W]:<{W}} {'/'.join(accepted)[:17]:<18} {r.intent:<18} {path:<5} {mark}")

    if run_llm:
        print("\n--- context cases (state-dependent, llm) ---")
        for msg, st, expected, via in CONTEXT_CASES:
            accepted = expected if isinstance(expected, tuple) else (expected,)
            r = intent_router.parse_intent(msg, st)
            ok = r.intent in accepted
            if ok:
                passed += 1
            else:
                failed += 1
                failures.append((msg, "/".join(accepted), r.intent, "ctx"))
            print(f"{msg[:W]:<{W}} {'/'.join(accepted)[:17]:<18} {r.intent:<18} llm   {'PASS' if ok else 'FAIL'}")
    else:
        skipped += len(CONTEXT_CASES)

    print("\n--- slot checks (keyword rules) ---")
    for msg, slot, want in SLOT_CASES:
        r = intent_router.parse_intent(msg)
        got = (r.slots or {}).get(slot)
        ok = got == want
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((msg, f"{slot}={want}", f"{slot}={got}", "slot"))
        print(f"{msg[:W]:<{W}} {slot}={want!r:<12} got {got!r:<14} {'PASS' if ok else 'FAIL'}")

    print("\n--- known bugs (do not fail while still broken) ---")
    fixed_bugs = []
    for msg, correct, broken, note in KNOWN_BUGS:
        r = intent_router.parse_intent(msg)
        if r.intent == "<llm-skipped>":
            print(f"{msg[:W]:<{W}} needs llm fallback — skipped (--no-llm)")
            continue
        if r.intent == broken:
            print(f"{msg[:W]:<{W}} still broken -> {r.intent}  (expected for now)")
        elif r.intent == correct:
            fixed_bugs.append(msg)
            print(f"{msg[:W]:<{W}} FIXED -> {r.intent}  ** move this into CASES **")
        else:
            failed += 1
            failures.append((msg, f"{correct} (or known-broken {broken})", r.intent, "bug"))
            print(f"{msg[:W]:<{W}} CHANGED -> {r.intent}  ** neither correct nor the known misroute — FAIL **")

    intent_router.parse_intent_with_openai = real_fallback

    print(f"\n{'='*40}\nPassed: {passed}  Failed: {failed}  Skipped (llm, --no-llm): {skipped}")
    if fixed_bugs:
        print(f"Known bugs now FIXED (update KNOWN_BUGS/CASES): {len(fixed_bugs)}")
    if failures:
        print("\nFailures:")
        for msg, want, got, kind in failures:
            print(f"  [{kind}] {msg!r}: expected {want}, got {got}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
