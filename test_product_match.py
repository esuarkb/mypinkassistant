"""Product-resolution regression tests for intent_router.best_matches().

The intent golden suite proves ROUTING; this proves the catalog matcher picks
the right PRODUCT. Added after weed-garden 2026-07-15 (c39): a bare "cleanser"
alias on Clear Proof + WRatio penalizing a true product's extra name tokens
made "timewise cleanser" resolve to Clear Proof (90) instead of a TimeWise
cleanser (53). Fix: scattered all-words-in-NAME boost in best_matches
(intent_router.py, just below the contiguous exact-phrase override). This is
the SECOND recurrence of the Clear Proof greedy-alias family (also 2026-07-09
"hydrating cleanser"), so pin it.

Run: venv/bin/python test_product_match.py   (offline, no LLM, no network)
"""
import sys
from mk_chat_core import load_catalog, get_catalog_path_for_language
from intent_router import best_matches

_CAT = load_catalog(get_catalog_path_for_language("en"))


def _top(query: str) -> str:
    m = best_matches(_CAT, query, limit=1)
    return m[0]["product_name"] if m else "(none)"


# (query, substring that MUST appear in the top product name)
CASES = [
    # --- the bug: brand + category must beat alias-only rivals ---
    ("timewise cleanser",           "TimeWise"),          # not Clear Proof, not MKMen
    ("timewise cleanser",           "Cleanser"),
    ("cleanser normal to dry",      "TimeWise"),          # brand-less but variant words in name
    ("cleanser normal to dry",      "Normal/Dry"),
    ("timewise 4 in 1 cleanser",    "TimeWise 4-in-1 Cleanser"),
    ("moisturizer normal to dry",   "TimeWise Antioxidant Moisturizer"),
    ("great heights mascara black", "Great Heights Mascara"),
    ("cc cream light to medium",    "Light to Medium"),

    # --- guards: prior deliberate decisions must NOT regress ---
    ("clear proof cleanser",        "Clear Proof Clarifying Cleansing Gel"),  # explicit alias
    ("face wash",                   "Clear Proof Clarifying Cleansing Gel"),  # kept: MKMen 7/15 decision
    ("mkmen face wash",             "MKMen Daily Facial Wash"),               # kept: MKMen 7/15 fix
    ("hydrating cleanser",          "Mary Kay Hydrating Cleanser"),           # kept: 2026-07-09 fix
    ("mattifying cleanser",         "Mary Kay Mattifying Cleanser"),
    ("charcoal mask",               "Clear Proof Deep-Cleansing Charcoal Mask"),

    # --- "for" stop-word (weed-garden 2026-07-17 F1): the two products whose
    # names contain "for" must still win their real queries on other words ---
    ("lotion for feet",             "Mint Bliss Energizing Lotion for Feet & Legs"),
    ("moisturizer for acne prone skin", "Clear Proof Oil-Free Moisturizer"),
]


def main() -> int:
    passed = failed = 0
    for query, needle in CASES:
        top = _top(query)
        ok = needle.lower() in top.lower()
        print(f"  {'PASS' if ok else 'FAIL'}  {query:30} -> {top}"
              f"{'' if ok else f'   (expected to contain: {needle!r})'}")
        passed += ok
        failed += not ok
    print(f"\n{'='*50}\nPassed: {passed}  Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
