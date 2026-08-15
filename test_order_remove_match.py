"""
Pins for MKChatEngine._name_matches (order-remove line matching) and the
same-SKU fragment-merge note in _format_order_confirm.

Origin: weed-garden 2026-08-15 (window 8/13-14). _name_matches returned False
on real product names containing "+" ("Define + Lift"), glued compounds
("eyeshadow" vs "Eye Shadow"), or when the spoken target carried stop-words
("the", "and") — which cascaded into the conjunction guard's "I can only
remove one item at a time" refusal and lost a real order (c100). The merge
note pins guard the companion fix: two differently-typed lines collapsing
into one SKU must be announced, never a silent x2.

Run: python test_order_remove_match.py   (offline, no LLM, no DB writes)
"""
from mk_chat_core import MKChatEngine
from mk_chat_core.ui_text import UI_EN

# (target, product name, expected)
NAME_CASES = [
    # the 2026-08-15 window failures — must match
    ("define and lift", "Mary Kay Lash Love Fanorama Define + Lift Mascara", True),
    ("shimmer eyeshadow, stick, copper nova", "Mary Kay Shimmer Eye Shadow Stick - Copper Nova", True),
    ("the luminous foundation", "TimeWise Luminous 3D Foundation - Beige N 210", True),
    # pre-existing behavior that must not regress
    ("dark brunette", "Mary Kay Precision Brow Liner - Dark Brunette", True),
    ("precision, brow, liner, dark, brunette", "Mary Kay Precision Brow Liner - Dark Brunette", True),
    ("apple and almond", "Apple & Almond Scented Cleansing Gel", True),
    ("cleansing gel", "Apple & Almond Scented Cleanser Gel", True),  # stem drift
    ("serum c+e", "TimeWise Replenishing Serum C+E", True),
    # NEGATIVE guards: a target naming TWO products must not match either
    # line alone — that keeps the conjunction guard rejecting real
    # multi-item removes ("remove X and Y" → "one item at a time")
    ("mascara and eyeliner", "Mary Kay Ultimate Mascara - Black", False),
    ("cheek brush and lipstick", "Mary Kay Cheek Brush", False),
    ("lotion, cleanser", "TimeWise 4-in-1 Cleanser Normal/Dry", False),
    ("apple and almond lotion", "White Peach & Silk Blossom Nourishing Body Lotion", False),
    ("foundation", "Mary Kay Cheek Brush", False),
]

_PROD = {"sku": "1234567", "product_name": "Silky Setting Powder Light to Medium", "price": 20.0}
_CUST = {"First Name": "Jane", "Last Name": "Doe"}


def _order(lines):
    return {"customer": _CUST, "customer_id": None, "lines": lines, "discounts": []}


# (label, lines, note_expected)
MERGE_CASES = [
    ("distinct fragments, same SKU -> note",
     [{"text": "silky", "qty": 1, "chosen": dict(_PROD)},
      {"text": "setting powder light to medium", "qty": 1, "chosen": dict(_PROD)}],
     True),
    ("single line qty 2 -> no note",
     [{"text": "2 powders", "qty": 2, "chosen": dict(_PROD)}],
     False),
    ("identical text twice (true repeat) -> no note",
     [{"text": "powder", "qty": 1, "chosen": dict(_PROD)},
      {"text": "Powder", "qty": 1, "chosen": dict(_PROD)}],
     False),
]


def main() -> int:
    eng = MKChatEngine()
    passed = failed = 0

    for target, name, want in NAME_CASES:
        got = eng._name_matches(target, name)
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  _name_matches({target!r}, {name[:38]!r}) = {got}"
              f"{'' if ok else f'   (expected {want})'}")
        passed += ok
        failed += not ok

    marker = UI_EN["order_merge_note"][:16]  # stable prefix of the note
    for label, lines, want in MERGE_CASES:
        text = eng._format_order_confirm(_order(lines), UI_EN)
        got = marker in text
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  merge note: {label}")
        passed += ok
        failed += not ok

    print(f"\n{'='*50}\nPassed: {passed}  Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
