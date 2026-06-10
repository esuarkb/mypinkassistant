"""Quick intent routing smoke test. Run with: python test_intent_routing.py"""
from intent_router import parse_intent

tests = [
    # --- FIXED: possessive orders should now be recent_orders ---
    ("Jeannie's orders in 2024",              "recent_orders"),
    ("Sarah's orders in January",             "recent_orders"),

    # --- FIXED: year in query should NOT flip to new_order ---
    ("What did Jeannie order in Jan 2024",    "recent_orders"),
    ("show me jeannie order in January 2024", "recent_orders"),
    ("what has she ordered in 2024",          "recent_orders"),

    # --- Real order entry: must still route to new_order ---
    # Note: "Jeannie ordered 2 X" → parse_intent returns recent_orders,
    # then mk_chat_core overrides to new_order via _looks_like_new_order_entry.
    # Test only covers parse_intent output here.
    ("Jeannie ordered 2 timewise sets",       "recent_orders"),  # overridden to new_order in app
    ("order for Jeannie",                     "new_order"),
    ("new order for sarah",                   "new_order"),
    ("sarah needs a timewise set and cleanser", "new_order"),

    # --- recent_orders: normal cases (incl. "all") ---
    ("all orders for Jeannie Furin",          "recent_orders"),
    ("show all of Jeannie's orders",          "recent_orders"),
    ("orders for Jeannie in 2024",            "recent_orders"),
    ("last order for sarah",                  "recent_orders"),
    ("recent orders for mary",                "recent_orders"),
    ("order history for jane",                "recent_orders"),
    ("what did sarah order",                  "recent_orders"),
    ("what has mary bought",                  "recent_orders"),
    ("show me her last order",                "recent_orders"),

    # --- data_query: aggregate / cross-customer ---
    ("who ordered in May",                    "data_query"),
    ("how many orders this month",            "data_query"),
    ("orders in march",                       "data_query"),
    ("total revenue last month",              "data_query"),
    ("who ordered the timewise set",          "data_query"),
    ("customers who never ordered",           "data_query"),
    ("who ordered just once",                 "data_query"),
    ("online orders this week",               "data_query"),

    # --- other intents ---
    ("new customer Jane Smith",               "new_customer"),
    ("Jane Smith info",                       "customer_info"),
    ("Jane's email",                          "customer_info"),
    ("who has birthdays this month",          "customer_info"),
    ("who hasn't ordered in 3 months",        "lapsed_customers"),
    ("top customers",                         "leaderboard"),
    ("how much has Jane spent",               "customer_spend"),
    ("my team",                               "unit_query"),
    ("who is inactive",                       "unit_query"),
    ("cancel",                                "cancel"),
]

W = 50
print(f"{'Message':<{W}} {'Expected':<18} {'Got':<18} OK?")
print("-" * (W + 42))
passed = failed = 0
failures = []
for msg, expected in tests:
    result = parse_intent(msg)
    ok = result.intent == expected
    passed += ok
    if not ok:
        failed += 1
        failures.append((msg, expected, result.intent))
    marker = "✅" if ok else "❌"
    print(f"{msg:<{W}} {expected:<18} {result.intent:<18} {marker}")

print()
print(f"Results: {passed}/{len(tests)} passed, {failed} failed")
if failures:
    print("\nFailed cases:")
    for msg, exp, got in failures:
        print(f"  '{msg}' → expected {exp}, got {got}")
