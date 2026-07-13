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

ROUTE_CASES exercise intent_router.route() — the full pipeline handle_message
dispatches on since the 2026-07-02 routing consolidation (keyword rules + LLM
fallback + the heuristic hijack chain: catalog matches, inventory phrasings,
look book, birthdays, follow-ups, pending-flow guards, ...). All deterministic.

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
    # Spanish — four UI_ES strings instruct "escribe cancelar" (fixed 2026-07-11)
    ("cancelar",                                "cancel",            "kw"),
    ("empezar de nuevo",                        "cancel",            "kw"),

    # --- chat_help (kw) ---
    ("help",                                    "chat_help",         "kw"),
    ("what can you do",                         "chat_help",         "kw"),

    # --- app_help (kw) ---
    ("app",                                     "app_help",          "kw"),
    ("how do i add the app to my home screen",  "app_help",          "kw"),
    ("install the app on my ipad",              "app_help",          "kw"),

    # --- mid-flow reply tokens must NOT call the LLM ---
    # With NO pending open, "yes"/"no" now return unknown deterministically
    # (weed-garden 2026-07-08 F4: they used to hit the bare-name rule and show
    # a random customer's card — "Yes" → Yessica Manzo). Still never LLM.
    # The mid-flow contract (pending open → bare-name path → pending layer
    # consumes) is pinned in ROUTE_CASES below.
    ("yes",                                     "unknown",           "kw"),
    ("no",                                      "unknown",           "kw"),
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
    # DECIDED 2026-07-11 (Brian): "who ordered <time>" defaults to CUSTOMERS
    # for everyone — a director asked it meaning customers and dead-ended
    # (weed-garden 2026-07-10, c39). Unit views require explicit consultant
    # phrasing ("which consultants have ordered this month" — pinned above).
    ("who ordered last month",                  "data_query",        "kw"),
    ("ordered last month",                      "data_query",        "kw"),
    ("who ordered last quarter?",               "data_query",        "kw"),

    # --- new_customer "create X" rule (positive pin for the F4 list-guard) ---
    ("create nichole giveaway",                 "new_customer",      "kw"),
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

    # --- customers by NAME (kw) — added 2026-07-04, live incident: LLM sent
    # these to customers_by_city and echoed "No customers found in Who Are My."
    ("who are my customers with the name, brenda?", "customer_info",  "kw"),
    ("customers named brenda",                  "customer_info",     "kw"),
    ("customers called brenda",                 "customer_info",     "kw"),

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
    # "what X does [name] use" — live 2026-07-02 (Lark): the LLM split two
    # near-identical phrasings between product_lookup and recent_orders;
    # now a deterministic kw rule
    ("what cleanser does nicole johnstone use", "recent_orders",     "kw"),
    ("what foundation does jane wear",          "recent_orders",     "kw"),
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
    # LLM splits order_add/new_order/unknown on this phrasing (drifted further
    # when inventory_help joined the classifier prompt 2026-07-06). VERIFIED
    # equivalent: all three produce the identical "Who is this order for?"
    # reply — the order parser catches it either way.
    ("now add a translucent powder",            ("order_add", "new_order", "unknown"), "llm"),

    # --- order_remove (llm only) ---
    ("remove ultimate mascara",                 "order_remove",      "llm"),
    ("remove 2 honey and luster",               "order_remove",      "llm"),
    ("remove one makeup remover",               "order_remove",      "llm"),

    # NOTE: notes_educate / mycustomers_link / bulk_text_educate are implemented
    # as route()-level rules (context/precedence-sensitive, like most of the
    # hijack chain), not in parse_intent()'s keyword tables — so their positive
    # and negative cases live in ROUTE_CASES / NEGATIVE_GUARD_CASES below, not here.

    # --- unit_query GSQ synonym (kw, in parse_intent's _unit_triggers) — added 2026-07-03 ---
    ("who is close to their gsq",               "unit_query",        "kw"),
    ("gsq status for my team",                  "unit_query",        "kw"),
]

# Messages that must NEVER be claimed by a given intent (regardless of what
# they DO route to). Distinct from CASES because these aren't asserting a
# single correct destination — some genuinely land on different intents call
# to call across repeated runs (e.g. LLM nondeterminism on order-ish text) —
# only that the new rule added on 2026-07-03 doesn't steal them.
# (message, forbidden_intent, note)
NEGATIVE_GUARD_CASES = [
    ("Misty Cameron add a note,  wants pink prism shimmer eye stick, barrier restore 1-1-3, foundation primer, translucent powder",
     "notes_educate",
     "filler 'add a note' inside a real order entry must still be parsed as an order"),
    ("text liz mayo a reminder", "bulk_text_educate", "single name must not be claimed"),
    ("send a reminder text to liz mayo", "bulk_text_educate", "single name must not be claimed"),
    ("can you create a text message so i can send out to previous orders?",
     "bulk_text_educate", "non-outreach phrasing must not be claimed"),
    ("Edit Bobbie hinski order to add 25% off", "edit_request",
     "order-edit phrasing must not be caught by the bare edit_request widening"),
    # weed-garden 2026-07-08 (F4): stray confirmations with no pending open
    # must not pass as bare names and fuzzy-match a random customer's card
    # ("Yes" → Yessica Manzo). Exact-word exclusion — real names unaffected.
    ("yes", "customer_info", "stray yes must not show a customer card"),
    ("no thanks", "customer_info", "stray no-thanks must not show a customer card"),
    ("Okay", "customer_info", "stray okay must not show a customer card"),
    # weed-garden 2026-07-09: "phone number" must never be caught by the new
    # part-number rule — the rule regex is scoped to part/item/sku specifically.
    ("what is jane doe's phone number", "product_lookup", "phone number must not trigger the part-number rule"),
    # weed-garden 2026-07-10 (F4): "create a list/report of …" is analytics,
    # not a person — must not prompt the new-customer form. "create nichole
    # giveaway" staying new_customer is pinned in CASES.
    ("Create a list of what I sold this week", "new_customer",
     "create-a-list must not hit the new-customer rule"),
    # "show" narrowed 2026-07-11: bare show + product words must not
    # fuzzy-search the product as a customer name
    ("show me pink lipsticks", "customer_info",
     "bare show must not claim product asks for customer lookup"),
    # weed-garden 2026-07-11 (F1/F2 guards):
    ("New customer Dana Doe birthday July 4 1980", "birthday_lookup",
     "customer entry with a birthday month must not become a birthday list"),
    ("did my customers sync", "customers_by_product",
     "city-guard rejects must not relocate to the product catch-all"),
    ("Add Deb Rivers to my customers", "customers_by_product",
     "city-guard rejects must not relocate to the product catch-all"),
    ("did my customers sync", "customers_by_city",
     "verb capture must not be claimed as a city"),
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
    # weed-garden 2026-07-07 (F2b): "City, State" + verbose/polite forms must
    # extract the city. The old end-anchored, comma-less pattern truncated at the
    # comma or grabbed the leading verb phrase ("No customers found in I Need A
    # List Of"); c114 typed Cleburne five ways with inconsistent results.
    ("customers in cleburne, texas",  "city",      "Cleburne, Texas"),
    ("give me a list of all my customers in cleburne, texas", "city", "Cleburne, Texas"),
    ("i need a list of customers from cleburne, texas with name and phone number", "city", "Cleburne, Texas"),
    ("customers in eau claire, wi",   "city",      "Eau Claire, Wi"),
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
# ROUTE_CASES — full-pipeline checks against intent_router.route(), which is
# what handle_message actually dispatches on since the 2026-07-02 routing
# consolidation. These exercise the heuristic ("hijack") rules that parse_intent
# alone can't answer: catalog matches, inventory phrasings, look book, etc.
# All deterministic (no LLM), so they run in --no-llm mode too.
# Format: (message, state_or_None, expected_route_intent)
# ---------------------------------------------------------------------------
_MID_FLOW = {"pending": {"kind": "order_confirm"}}  # any active pending flow

ROUTE_CASES = [
    # graduated from FUTURE_CORE_CASES 2026-07-02 (step-2 consolidation done)
    ("charcoal mask",                            None, "product_lookup"),   # bare catalog match
    ("lifting serum",                            None, "product_lookup"),
    ("how many timewise sets do i have on hand", None, "inventory_count"),
    ("spanish look book",                        None, "look_book"),
    ("what should i order",                      None, "inventory_low_stock"),
    # hijack-chain rules
    ("show all satin hands",                     None, "show_all_products"),
    ("print my inventory",                       None, "inventory_print"),
    ("add 3 satin hands to inventory",           None, "inventory_write"),
    ("add 3 satin hands",                        None, "inventory_guardrail"),
    ("keep 3 charcoal mask on hand",             None, "inventory_threshold"),
    ("delete jane doe",                          None, "delete_customer"),
    ("my referral link",                         None, "referral"),
    ("update jane's phone number",               None, "edit_request"),
    ("birthdays this month",                     None, "birthday_lookup"),
    ("follow ups",                               None, "followup"),
    # stubbed/offline LLM -> customers_by_product rule; live LLM often says
    # customers_by_city, whose handler product-search fallback gives the same
    # answer (identical to pre-consolidation behavior) — both are correct
    ("who are my retinol customers",             None, ("customers_by_product", "customers_by_city")),
    ("how much is the charcoal mask",            None, "product_lookup"),   # price query
    # --- weed-garden fixes 2026-07-04 (all live incidents from 7/03 logs) ---
    ("what does the charcoal mask cost",         None, "product_lookup"),   # cost-anchored form must keep working
    ("What does par mean on the inventory spreadsheet", None, "inventory_help"),  # was product_lookup conf 1.0
    # --- feature-help gate 2026-07-06: HOW-a-feature-works questions get the
    # help bubble, not the action (live: "How do I add inventory?" ×2 → unknown;
    # "how does inventory work" → dumped the full inventory list) ---
    ("how does inventory work",                  None, "inventory_help"),
    ("How do I add inventory?",                  None, "inventory_help"),
    ("what can the inventory do",                None, "inventory_help"),
    # action guards for the gate (siblings already pinned above/elsewhere):
    ("what do i need to reorder",                None, "inventory_low_stock"),
    # --- feature-help topics round 2 (2026-07-06, Brian-approved bubbles) ---
    ("how do orders work",                       None, "order_help"),
    # general "how does the whole thing work" → cheat sheet, not a dead-end
    # (live 2026-07-06: "How does chat work" → "couldn't tell if customer or order")
    ("how does chat work",                       None, "chat_help"),
    ("how does this work",                       None, "chat_help"),
    ("how do i get started",                     None, "chat_help"),
    ("how do i place an order",                  None, "order_help"),
    ("how do i cancel this order",               None, "order_help"),      # order beats billing
    ("how do followups work",                    None, "followup_help"),
    ("what are follow ups",                      None, "followup_help"),
    ("how does the sync work",                   None, "sync_help"),
    ("how do i cancel my subscription",          None, "billing_help"),
    ("is my data safe",                          None, "privacy_help"),
    # guards: actions/data-questions must never become help bubbles
    ("do i have any followups",                  None, "followup"),
    ("what is my referral link",                 None, "referral"),
    ("what foundations do i have in stock",      None, "inventory_count"),  # was a catalog price list
    # --- weed-garden 2026-07-07: "<name> ordered <products>" is order ENTRY, not
    # an order-history lookup. c39 fought this ~15x — single items and "ordered:"
    # colon lists dead-ended in recent_orders word-salad ("I couldn't find blue
    # eyeliner in your saved customers"). Override now catches the active-verb
    # statement shape (_looks_like_new_order_entry); interrogative/history
    # phrasings still stay recent_orders. ---
    ("dana rivers ordered makeup remover",       None, "new_order"),          # single item, was recent_orders
    ("dana ordered: spark change, micellar water, black eyeliner", None, "new_order"),  # colon list, was recent_orders
    ("dana rivers ordered makeup finishing spray", None, "new_order"),
    # negative guards — genuine lookups must STAY recent_orders:
    ("what did dana order",                      None, "recent_orders"),
    ("who last ordered under eye corrector",     None, "recent_orders"),      # cross-customer lookup, not entry
    ("recent orders for dana",                   None, "recent_orders"),
    # catalog-search fixes 2026-07-03 (search_terms aliases + compound-word
    # normalization + trailing "ingredients" — all were June production failures)
    ("dwl",                                      None, "product_lookup"),   # search_terms alias
    ("travel set",                               None, "product_lookup"),   # alias on the Go Sets
    ("lipgloss",                                 None, "product_lookup"),   # compound-word fix
    ("Makeup remover ingredients",               None, "product_lookup"),   # trailing "ingredients"
    ("Facial peel ingredients",                  None, "product_lookup"),
    # guards: the pre-filter typo fallback must never let non-product words
    # claim product_lookup outside a product context (they fuzz above 70)
    ("yes",                                      None, ("customer_info", "unknown", "<llm-skipped>")),
    ("skip",                                     None, ("customer_info", "unknown", "<llm-skipped>")),
    ("waterproo",                                None, ("customer_info", "unknown", "<llm-skipped>")),  # half-typed customer search, live 2026-06-28
    # submitted-order edits (live incident 2026-07-02, Kimberly/Judy Pasko):
    # with no draft open, add/remove against an existing order gets the
    # educate-and-point-at-MyCustomers reply instead of a phantom new order.
    # First two are her exact messages incl. the iOS curly apostrophe.
    ("Add raspberry ice to Judy Pasko‘s order", None, "submitted_order_edit"),
    ("Remove Judy Pasko‘s order for lipstick",  None, "submitted_order_edit"),
    ("remove july 3 order for lipstick",         None, "submitted_order_edit"),
    ("add satin hands to her order",             None, "submitted_order_edit"),
    ("cancel judy's order",                      None, "submitted_order_edit"),
    ("delete that order from yesterday",         None, "submitted_order_edit"),
    ("delete judy doe",                          None, "delete_customer"),     # no "order" word — delete flow untouched
    # pending-flow guards: mid-flow, guarded rules must NOT claim the message,
    # so the pending flow consumes it (route falls through to the base intent)
    ("charcoal mask",                            _MID_FLOW, "customer_info"),  # bare-name rule; pending flow eats it
    # weed-garden 2026-07-08 F4: mid-flow confirm tokens MUST stay on the
    # deterministic bare-name path (1,360x/30d, never LLM) — pending consumes.
    ("yes",                                      _MID_FLOW, "customer_info"),
    ("no",                                       _MID_FLOW, "customer_info"),
    # …but with NO pending, the same tokens are unknown (fallback bubble),
    # never a fuzzy customer-card match.
    ("yes",                                      None,      "unknown"),
    ("no thanks",                                None,      "unknown"),
    ("thank you",                                None,      "unknown"),
    ("okay",                                     None,      "unknown"),
    ("spanish look book",                        _MID_FLOW, "look_book"),      # look book works even mid-order
    ("print my inventory",                       _MID_FLOW, "inventory_print"),
    # mid-draft add/remove must NOT be claimed by the submitted-order rule —
    # the pending flow edits the draft (route falls through to the base intent)
    ("add raspberry ice to the order",           _MID_FLOW, ("order_add", "<llm-skipped>", "unknown")),
    ("remove the lipstick from judy's order",    _MID_FLOW, ("order_remove", "<llm-skipped>", "unknown")),

    # --- notes_educate / mycustomers_link / bulk_text_educate — added 2026-07-03 ---
    ("can you add a note to meghan froemke",     None, "notes_educate"),
    ("link to mycustomers",                      None, "mycustomers_link"),
    ("open mycustomers",                         None, "mycustomers_link"),
    # "mycustomers" mentioned in a non-link context must NOT be claimed by the
    # link rule — the specialized educate replies are more helpful (both carry
    # the same link anyway)
    ("add a note to meghan in mycustomers",      None, "notes_educate"),
    ("update her address in mycustomers",        None, "edit_request"),
    ("Can you send a reminder text to Liz Mayo, Dana Smith Laura Miller Jessica Beazley, Amie Cauley, Sherry Golden Mackenzie Cox", None, "bulk_text_educate"),
    # single-name text asks show that customer's card — it has the phone number
    # to text from (owner decision 2026-07-03); multi-name stays on the educate reply
    ("Send a reminder text to Jane Doe",          None, "customer_info"),
    ("send a text to jane doe",                   None, "customer_info"),
    ("send a text to all my customers",           None, "bulk_text_educate"),
    # the exact phrase the bulk_text_educate copy tells consultants to type must
    # route deterministically to followup (was an LLM coin-flip vs lapsed_customers)
    ("do i have any followups",                   None, "followup"),
    ("Do I have any follow ups",                  None, "followup"),

    # --- edit_request bare-form widening — added 2026-07-03, owner-approved ---
    ("edit this customer",                       None, "edit_request"),
    ("edit her info",                             None, "edit_request"),
    ("update this customer",                      None, "edit_request"),
    # negative guard: order-edit phrasings must still go to edit_request via
    # the pre-existing submitted-order-edit-adjacent path, NOT be broken by
    # the new bare-form widening (this is the exact live-incident phrasing)
    ("Edit Bobbie hinski order to add 25% off",  None, ("order_add", "order_adjust", "submitted_order_edit", "<llm-skipped>", "unknown")),

    # --- part-number routing — added weed-garden 2026-07-09 (c29 gave up after
    # 2 attempts asking "what is the part number of natural lipstick"; the
    # customer_info catch-all claimed it and dead-ended) ---
    ("what is the part number of natural lipstick", None, "product_lookup"),
    ("part number for cc cream",                    None, "product_lookup"),
    ("sku for hydrating cleanser",                  None, "product_lookup"),
    # order-context guards: sku/part-number INSIDE an order must never be
    # hijacked into a lookup (supervision catch, 2026-07-10 — the unguarded
    # rule stole "New order … sku 10233551" from new_order)
    ("New order for Dana Rivers sku 10233551",      None, "new_order"),
    ("add sku 10233551 to the order",               _MID_FLOW, ("order_add", "<llm-skipped>", "unknown")),

    # --- weed-garden 2026-07-10 batch ---
    # F1: gem street names must not substring-match Star levels; the paste
    # goes to customer_info so a pending new-customer flow can consume it
    ("Dana Rivers\n\nStreet Address: 42926 Pearlwood Dr\nCity: Lancaster\nState / Province: CA",
     {"pending": {"kind": "new_customer"}}, "customer_info"),
    ("show me pearl consultants",                   None, "unit_query"),   # real gem word still works
    # F2: "who ordered <time>" is a customer data question, never a product
    # search (the old guard leaked "quarter?" punctuation and "past…days")
    ("who ordered last quarter?",                   None, "data_query"),
    ("Who ordered in the past 90 days?",            None, "data_query"),
    ("who ordered charcoal mask",                   None, "customers_by_product"),  # real products stay
    # F3: "make a note" reaches the educate bubble
    ("Make a note that Dana likes the satin hands set", None, "notes_educate"),

    # --- "show" narrowed 2026-07-11: person-signal required (possessive or
    # contact word); product/team shapes fall through to better homes ---
    ("show me robyn depagter's contact information", None, "customer_info"),
    ("show me time wise customers",                  None, "customers_by_product"),

    # --- weed-garden 2026-07-11 batch (built 2026-07-12) ---
    # F1: month-NAMED birthday queries (c78 fought 4 phrasings; rule only knew
    # relative periods). Full-sentence case also exercises the F2 city guard —
    # the reverse pattern had claimed "Can You Tell Me Which One Of My" as a city.
    ("Can you tell me which one of my customers have a birthday in the month of July and on what day their birthdays are",
     None, "birthday_lookup"),
    ("July customer birthdays",                      None, "birthday_lookup"),
    ("who has a birthday in the month of july",      None, "birthday_lookup"),
    ("Does Gail have a birthday in July",            None, "birthday_lookup"),
    ("birthdays in december",                        None, "birthday_lookup"),
    ("who has a birthday in may",                    None, "birthday_lookup"),   # "may" needs month-ish context
    ("customers who may have a birthday this week",  None, "birthday_lookup"),   # modal "may" must not force month:5
    # F2: reverse "[X] customers" capture guards — legit cities stay, verb-y
    # captures fall through (and must NOT relocate to customers_by_product)
    ("Sheboygan customers",                          None, "customers_by_city"),
    ("eau claire customers",                         None, "customers_by_city"),

    # --- "[product] customers" catalog-yield (weed-garden 2026-07-12): a
    # PRODUCT word grabbed as a city now falls through to product-buyers.
    # Discriminator = every word is a catalog word (separates "satin hands"
    # from "grand island"). ---
    ("repair customers",                             None, "customers_by_product"),
    ("timewise customers",                           None, "customers_by_product"),
    ("satin hands customers",                        None, "customers_by_product"),
    # cities that share ONE catalog word must STAY city:
    ("Eau Claire customers",                         None, "customers_by_city"),
    ("Grand Island customers",                       None, "customers_by_city"),
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

    print("\n--- route() pipeline checks (deterministic, full chain) ---")
    from mk_chat_core import load_catalog, get_catalog_path_for_language
    _catalog = load_catalog(get_catalog_path_for_language("en"))
    for msg, st, expected in ROUTE_CASES:
        accepted = expected if isinstance(expected, tuple) else (expected,)
        r = intent_router.route(msg, dict(st) if st else {}, _catalog)
        ok = r.intent in accepted
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((msg, "/".join(accepted), r.intent, "route"))
        _pend = " [mid-flow]" if (st or {}).get("pending") else ""
        print(f"{(msg + _pend)[:W]:<{W}} {'/'.join(accepted)[:17]:<18} {r.intent:<18} route {'PASS' if ok else 'FAIL'}")

    print("\n--- negative guards (must NEVER be claimed by the named intent) ---")
    for msg, forbidden, note in NEGATIVE_GUARD_CASES:
        r = intent_router.route(msg, {}, _catalog)
        ok = r.intent != forbidden
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((msg, f"NOT {forbidden}", r.intent, "neg-guard"))
        print(f"{msg[:W]:<{W}} forbidden={forbidden:<16} got {r.intent:<14} {'PASS' if ok else 'FAIL'}  ({note})")

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
