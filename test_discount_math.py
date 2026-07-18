"""Discount/tax feature unit tests (2026-07-18). Offline, no LLM, no network.

Covers: extract_order_modifiers (phrase → modifier), is_pure_modifier_item
(LLM item-leak filter), and MKChatEngine._order_money (clamps + tax base —
the single source of truth for confirm display, DB save, and job payload).

Run: venv/bin/python test_discount_math.py
"""
from mk_chat_core.order_parse import extract_order_modifiers as eom, is_pure_modifier_item as ipmi
from mk_chat_core.engine import MKChatEngine

money = MKChatEngine._order_money

passed = failed = 0
def check(label, got, want):
    global passed, failed
    ok = got == want
    passed += ok; failed += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))

# ---- extract_order_modifiers ----
def slim(m):
    """Comparable view: drop the discounts list, keep legacy keys."""
    return {k: v for k, v in m.items() if k != "discounts"}

check("pct off",        slim(eom("New order for Jane: lipstick, 20% off")), {"discount_type": "%", "discount_value": 20.0})
check("pct discount",   slim(eom("add a 30% discount")),                    {"discount_type": "%", "discount_value": 30.0})
check("dollar off",     slim(eom("$5 off")),                                {"discount_type": "$", "discount_value": 5.0})
check("dollars off",    slim(eom("give her 10 dollars off")),               {"discount_type": "$", "discount_value": 10.0})
check("tax pct",        eom("Add 7% sales tax and she has fully paid"),     {"tax_percent_override": 7.0})
check("tax of pct",     eom("sales tax of 8.25%"),                          {"tax_percent_override": 8.25})
check("no tax",         eom("no tax"),                                      {"no_tax": True})
check("tax not disc",   "discount_type" in eom("add 7% sales tax"),         False)
check("plain items",    eom("two cc creams light to medium"),               {})
check("tax + disc",     slim(eom("order: mask, 20% off, 7% sales tax")),    {"tax_percent_override": 7.0, "discount_type": "%", "discount_value": 20.0})

# multi-mention with item targets (Brian's two-discount test 2026-07-18)
_m = eom("new order for Jane doe, charcoal mask at 20% off, repair set at $100 off")
_ds = _m.get("discounts") or []
check("two mentions found", len(_ds), 2)
check("mention 1 scoped",  (_ds[0]["type"], _ds[0]["value"], "charcoal mask" in _ds[0]["target"]) if _ds else None, ("%", 20.0, True))
check("mention 2 scoped",  (_ds[1]["type"], _ds[1]["value"], "repair set" in _ds[1]["target"]) if len(_ds) > 1 else None, ("$", 100.0, True))
check("no legacy on multi", "discount_type" in _m, False)

# NO-COMMA phrasing (Brian round 2 2026-07-18): "mask 20% off and a repair set
# $50 off" is one segment with TWO discounts — both must extract, scoped.
_m = eom("new order for Jane Doe charcoal mask 20% off and a repair set $50 off")
_ds = _m.get("discounts") or []
check("no-comma: two mentions", len(_ds), 2)
check("no-comma m1", (_ds[0]["type"], _ds[0]["value"], _ds[0]["target"]) if _ds else None, ("%", 20.0, "charcoal mask"))
check("no-comma m2", (_ds[1]["type"], _ds[1]["value"], _ds[1]["target"]) if len(_ds) > 1 else None, ("$", 50.0, "repair set"))

# three mentions in one message
_ds = (eom("order for Kim: mask $5 off, set $10 off, lipstick 50% off").get("discounts") or [])
check("three mentions", [(d["type"], d["value"]) for d in _ds], [("$", 5.0), ("$", 10.0), ("%", 50.0)])

# ---- is_pure_modifier_item ----
check("item leak pct",  ipmi("20% off"), True)
check("item leak tax",  ipmi("7% sales tax"), True)
check("item leak no tax", ipmi("no tax"), True)
check("real product",   ipmi("charcoal mask"), False)
check("product w/ pct phrase", ipmi("clinical solutions retinol 0.5"), False)
check("empty",          ipmi(""), False)

# ---- _order_money ----
def mk_order(prices_qtys, **kw):
    lines = [{"qty": q, "chosen": {"price": p, "product_name": "X", "sku": "1"}} for p, q in prices_qtys]
    o = {"lines": lines, "fulfillment_method": kw.pop("fulfillment", "inventory")}
    o.update(kw)
    return o

m = money(mk_order([(26.0, 1)], discount_type="%", discount_value=20, tax_rate=8.25))
check("pct + rate tax", (m["discount_amount"], m["tax_amount"], m["grand_total"]), (5.20, 1.72, 22.52))

m = money(mk_order([(26.0, 1)], discount_type="$", discount_value=5, tax_percent_override=7.0, tax_rate=8.25))
check("dollar + override", (m["discount_amount"], m["tax_percent"], m["tax_amount"], m["grand_total"]), (5.0, 7.0, 1.47, 22.47))

# over-total rule (Brian 2026-07-18): discounts > retail total → apply NONE + flag
m = money(mk_order([(26.0, 1)], discount_type="$", discount_value=500))
check("over-total -> none applied", (m["discount_amount"], m["discount_over_total"], m["grand_total"]), (0.0, True, 26.0))

m = money(mk_order([(100.0, 1)], discount_type="%", discount_value=150))      # % still capped at 100 (=free, not over)
check("clamp % to 100", (m["discount_amount"], m["discount_over_total"]), (100.0, False))

m = money(mk_order([(26.0, 1)], discount_type="%", discount_value=20, tax_rate=8.25, no_tax=True))
check("no_tax kills rate", (m["tax_amount"], m["grand_total"]), (0.0, 20.80))

m = money(mk_order([(26.0, 1)], discount_type="%", discount_value=20, tax_rate=8.25, fulfillment="cds"))
check("cds: no discount/tax", (m["discount_amount"], m["tax_amount"], m["grand_total"]), (0.0, 0.0, 26.0))

m = money(mk_order([(26.0, 2), (32.0, 1)], tax_rate=8.25))                    # tax only, multi-item
check("tax only multi", (m["subtotal"], m["tax_amount"], m["grand_total"]), (84.0, 6.93, 90.93))

m = money(mk_order([(26.0, 1)]))                                              # nothing set = today's behavior
check("no modifiers", (m["discount_amount"], m["tax_amount"], m["grand_total"]), (0.0, 0.0, 26.0))

# skipped lines excluded from subtotal
o = mk_order([(26.0, 1)], discount_type="%", discount_value=50)
o["lines"].append({"qty": 1, "chosen": {"price": 99.0, "product_name": "S", "sku": "2", "_skipped": True}})
check("skipped line excluded", money(o)["subtotal"], 26.0)

# ---- mention resolution (item-scoped discounts; Brian's test 2026-07-18) ----
def mk_named(prices, **kw):
    lines = [{"qty": 1, "chosen": {"price": p, "product_name": n, "sku": str(i)}} for i, (n, p) in enumerate(prices)]
    o = {"lines": lines, "fulfillment_method": "inventory"}
    o.update(kw); return o

# 20% scoped to the $26 mask + $100 off the $230 set = 5.20 + 100 = 105.20 (rec '$')
o = mk_named([("Clear Proof Deep-Cleansing Charcoal Mask", 26.0), ("TimeWise Repair Volu-Firm Set", 230.0)],
             discount_mentions=[{"type": "%", "value": 20.0, "target": "charcoal mask"},
                                {"type": "$", "value": 100.0, "target": "repair set"}],
             tax_rate=8.25)
m = money(o)
check("scoped sum", (m["discount_amount"], m["rec_type"], m["rec_value"]), (105.20, "$", 105.20))
check("scoped sum tax", m["tax_amount"], round((256.0 - 105.20) * 0.0825, 2))

# $100 off a $40 item, order total $66 → under total, applies in FULL (no per-item cap)
o = mk_named([("TimeWise Repair Volu-Firm The Go Set", 40.0), ("Charcoal Mask", 26.0)],
             discount_mentions=[{"type": "$", "value": 50.0, "target": "go set"}])
m = money(o)
check("no per-item cap", (m["discount_amount"], m["discount_over_total"]), (50.0, False))

# $100 off the $40 Go Set alone → over the $40 retail total → none applied + flag
o = mk_named([("TimeWise Repair Volu-Firm The Go Set", 40.0)],
             discount_mentions=[{"type": "$", "value": 100.0, "target": "go set"}])
m = money(o)
check("mentions over-total -> none", (m["discount_amount"], m["discount_over_total"]), (0.0, True))

# single scoped % hits only its item, records as $
o = mk_named([("Charcoal Mask", 26.0), ("Repair Set", 230.0)],
             discount_mentions=[{"type": "%", "value": 20.0, "target": "charcoal mask"}])
m = money(o)
check("single scoped pct", (m["discount_amount"], m["rec_type"]), (5.20, "$"))

# unmatched target falls back to order-level
o = mk_named([("Charcoal Mask", 26.0)],
             discount_mentions=[{"type": "$", "value": 5.0, "target": "zzz nonexistent zzz"}])
check("unmatched target -> order level", money(o)["discount_amount"], 5.0)

# single UNtargeted % via mentions keeps the % record
o = mk_named([("Charcoal Mask", 26.0)],
             discount_mentions=[{"type": "%", "value": 20.0, "target": ""}])
m = money(o)
check("untargeted pct rec", (m["discount_amount"], m["rec_type"], m["rec_value"]), (5.20, "%", 20.0))

print(f"\n{'='*50}\nPassed: {passed}  Failed: {failed}")
raise SystemExit(1 if failed else 0)
