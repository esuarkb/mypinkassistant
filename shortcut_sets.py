# shortcut_sets.py
#
# Simple shorthand bundle expansions for common handwritten sales-slip set names.
# These expand into item text that your normal catalog matching flow can resolve.
#
# Structure:
#   SHORTCUT_SETS = {
#       "alias": {
#           "display_name": "...",
#           "items": [{"text": "...", "qty": 1}, ...],
#       }
#   }
#
# Notes:
# - Keep item text close to how products appear in your catalog.
# - For ambiguous bundles, use broad-but-meaningful phrases so your existing
#   matching / yes-no flow can clarify variants.
# - You can add more aliases later without touching chat logic much.

SHORTCUT_SETS = {
    # -------------------------
    # Love Your Skin
    # -------------------------
    "repair volu firm set": {
        "display_name": "Repair Volu-Firm Set",
        "items": [
            {"text": "TimeWise Repair Volu-Firm Foaming Cleanser", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Lifting Serum", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Day Cream SPF 30", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Night Cream with Retinol", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Eye Renewal Cream", "qty": 1},
        ],
    },
    "repair set": {
        "display_name": "Repair Volu-Firm Set",
        "items": [
            {"text": "TimeWise Repair Volu-Firm Foaming Cleanser", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Lifting Serum", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Day Cream SPF 30", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Night Cream with Retinol", "qty": 1},
            {"text": "TimeWise Repair Volu-Firm Eye Renewal Cream", "qty": 1},
        ],
    },

    "miracle set": {
        "display_name": "Miracle Set",
        "items": [
            {"text": "TimeWise Miracle Set cleanser", "qty": 1},
            {"text": "TimeWise Miracle Set daytime defender", "qty": 1},
            {"text": "TimeWise Miracle Set nighttime recovery", "qty": 1},
            {"text": "TimeWise Miracle Set moisturizer", "qty": 1},
        ],
    },
    "new skincare set": {
        "display_name": "Miracle Set",
        "items": [
            {"text": "TimeWise Miracle Set cleanser", "qty": 1},
            {"text": "TimeWise Miracle Set daytime defender", "qty": 1},
            {"text": "TimeWise Miracle Set nighttime recovery", "qty": 1},
            {"text": "TimeWise Miracle Set moisturizer", "qty": 1},
        ],
    },

    "mk men regimen": {
        "display_name": "MK Men Regimen",
        "items": [
            {"text": "MK Men Facial Wash", "qty": 1},
            {"text": "MK Men Ultimate Moisturizer", "qty": 1},
            {"text": "MK Men Shave Cream", "qty": 1},
        ],
    },
    "men regimen": {
        "display_name": "MK Men Regimen",
        "items": [
            {"text": "MK Men Facial Wash", "qty": 1},
            {"text": "MK Men Ultimate Moisturizer", "qty": 1},
            {"text": "MK Men Shave Cream", "qty": 1},
        ],
    },

    "clear proof set": {
        "display_name": "Clear Proof Set",
        "items": [
            {"text": "Clear Proof cleanser", "qty": 1},
            {"text": "Clear Proof toner", "qty": 1},
            {"text": "Clear Proof moisturizer", "qty": 1},
            {"text": "Clear Proof acne treatment gel", "qty": 1},
        ],
    },
    "acne set": {
        "display_name": "Clear Proof Set",
        "items": [
            {"text": "Clear Proof cleanser", "qty": 1},
            {"text": "Clear Proof toner", "qty": 1},
            {"text": "Clear Proof moisturizer", "qty": 1},
            {"text": "Clear Proof acne treatment gel", "qty": 1},
        ],
    },

    "basic set": {
        "display_name": "Basic Set",
        "items": [
            {"text": "Mary Kay basic set cleanser", "qty": 1},
            {"text": "Mary Kay basic set scrub", "qty": 1},
            {"text": "Mary Kay basic set toner", "qty": 1},
            {"text": "Mary Kay basic set moisturizer", "qty": 1},
        ],
    },

    "clinical solutions": {
        "display_name": "Clinical Solutions",
        "items": [
            {"text": "Clinical Solutions Retinol", "qty": 1},
        ],
    },
    "retinol set": {
        "display_name": "Clinical Solutions",
        "items": [
            {"text": "Clinical Solutions Retinol", "qty": 1},
        ],
    },

    "revealing radiance": {
        "display_name": "Revealing Radiance",
        "items": [
            {"text": "Revealing Radiance Facial Peel", "qty": 1},
        ],
    },
    "radiance set": {
        "display_name": "Revealing Radiance",
        "items": [
            {"text": "Revealing Radiance Facial Peel", "qty": 1},
        ],
    },

    "microderm set": {
        "display_name": "Microderm Set",
        "items": [
            {"text": "TimeWise Microdermabrasion Refine", "qty": 1},
            {"text": "TimeWise Microdermabrasion Pore Minimizer", "qty": 1},
        ],
    },
    "microdermabrasion set": {
        "display_name": "Microderm Set",
        "items": [
            {"text": "TimeWise Microdermabrasion Refine", "qty": 1},
            {"text": "TimeWise Microdermabrasion Pore Minimizer", "qty": 1},
        ],
    },

    # CS Boosters is intentionally broad because sheet says "Pick 2"
    "cs boosters": {
        "display_name": "CS Boosters",
        "items": [
            {"text": "Clinical Solutions booster", "qty": 2},
        ],
    },
    "boosters": {
        "display_name": "CS Boosters",
        "items": [
            {"text": "Clinical Solutions booster", "qty": 2},
        ],
    },

    "masking set": {
        "display_name": "Masking Set",
        "items": [
            {"text": "Clear Proof charcoal mask", "qty": 1},
            {"text": "moisture mask", "qty": 1},
            {"text": "mask applicator", "qty": 1},
        ],
    },
    "mask set": {
        "display_name": "Masking Set",
        "items": [
            {"text": "Clear Proof charcoal mask", "qty": 1},
            {"text": "moisture mask", "qty": 1},
            {"text": "mask applicator", "qty": 1},
        ],
    },

    "eye love this set": {
        "display_name": "Eye Love This Set",
        "items": [
            {"text": "Hydrogel Eye Patches", "qty": 1},
            {"text": "Instant Puffiness Reducer", "qty": 1},
        ],
    },

    # -------------------------
    # Love Your Look
    # -------------------------
    "eye candy set": {
        "display_name": "Eye Candy Set",
        "items": [
            {"text": "eye makeup remover", "qty": 1},
            {"text": "mascara", "qty": 1},
            {"text": "eye liner", "qty": 1},
        ],
    },

    "flawless face set": {
        "display_name": "Flawless Face Set",
        "items": [
            {"text": "foundation primer", "qty": 1},
            {"text": "foundation brush", "qty": 1},
            {"text": "foundation", "qty": 1},
        ],
    },
    "face set": {
        "display_name": "Flawless Face Set",
        "items": [
            {"text": "foundation primer", "qty": 1},
            {"text": "foundation brush", "qty": 1},
            {"text": "foundation", "qty": 1},
        ],
    },

    "professional brush set": {
        "display_name": "Professional Brush Set",
        "items": [
            {"text": "zip organizer bag", "qty": 1},
            {"text": "cheek brush", "qty": 1},
            {"text": "all over powder brush", "qty": 1},
            {"text": "all over eyeshadow brush", "qty": 1},
            {"text": "eye smudger brush", "qty": 1},
            {"text": "eye crease brush", "qty": 1},
        ],
    },
    "brush set": {
        "display_name": "Professional Brush Set",
        "items": [
            {"text": "zip organizer bag", "qty": 1},
            {"text": "cheek brush", "qty": 1},
            {"text": "all over powder brush", "qty": 1},
            {"text": "all over eyeshadow brush", "qty": 1},
            {"text": "eye smudger brush", "qty": 1},
            {"text": "eye crease brush", "qty": 1},
        ],
    },

    "luscious lips set": {
        "display_name": "Luscious Lips Set",
        "items": [
            {"text": "lip liner", "qty": 1},
            {"text": "lip gloss", "qty": 1},
            {"text": "lipstick", "qty": 1},
        ],
    },
    "lips set": {
        "display_name": "Luscious Lips Set",
        "items": [
            {"text": "lip liner", "qty": 1},
            {"text": "lip gloss", "qty": 1},
            {"text": "lipstick", "qty": 1},
        ],
    },

    "finishing set": {
        "display_name": "Finishing Set",
        "items": [
            {"text": "finishing spray", "qty": 1},
            {"text": "all over powder brush", "qty": 1},
            {"text": "translucent powder", "qty": 1},
        ],
    },

    "dash out the door set": {
        "display_name": "Dash Out The Door Set",
        "items": [
            {"text": "liquid eye color", "qty": 1},
            {"text": "cheek color", "qty": 1},
            {"text": "mascara", "qty": 1},
            {"text": "lip gloss", "qty": 1},
            {"text": "undereye corrector", "qty": 1},
        ],
    },
    "dash out door set": {
        "display_name": "Dash Out The Door Set",
        "items": [
            {"text": "liquid eye color", "qty": 1},
            {"text": "cheek color", "qty": 1},
            {"text": "mascara", "qty": 1},
            {"text": "lip gloss", "qty": 1},
            {"text": "undereye corrector", "qty": 1},
        ],
    },
    "dash out door": {
        "display_name": "Dash Out The Door Set",
        "items": [
            {"text": "liquid eye color", "qty": 1},
            {"text": "cheek color", "qty": 1},
            {"text": "mascara", "qty": 1},
            {"text": "lip gloss", "qty": 1},
            {"text": "undereye corrector", "qty": 1},
        ],
    },

    # -------------------------
    # Love the extras
    # -------------------------
    "satin hands and lips set": {
        "display_name": "Satin Hands & Lips Set",
        "items": [
            {"text": "satin hands set", "qty": 1},
            {"text": "satin lips set", "qty": 1},
        ],
    },
    "satin hands & lips set": {
        "display_name": "Satin Hands & Lips Set",
        "items": [
            {"text": "satin hands set", "qty": 1},
            {"text": "satin lips set", "qty": 1},
        ],
    },
    "satin hands and lips": {
        "display_name": "Satin Hands & Lips Set",
        "items": [
            {"text": "satin hands set", "qty": 1},
            {"text": "satin lips set", "qty": 1},
        ],
    },

    "toning lotion set": {
        "display_name": "Toning Lotion Set",
        "items": [
            {"text": "targeted action toning lotion", "qty": 1},
            {"text": "cc cream", "qty": 1},
        ],
    },
    "toning lotion": {
        "display_name": "Toning Lotion Set",
        "items": [
            {"text": "targeted action toning lotion", "qty": 1},
            {"text": "cc cream", "qty": 1},
        ],
    },

    "hello clean set": {
        "display_name": "Hello Clean Set",
        "items": [
            {"text": "2-in-1 wash and shave gel", "qty": 1},
            {"text": "hydrating body lotion", "qty": 1},
            {"text": "facial mineral sunscreen", "qty": 1},
        ],
    },

    "perfect palette": {
        "display_name": "Perfect Palette",
        "items": [
            {"text": "perfect palette", "qty": 1},
            {"text": "eye shadow", "qty": 3},
            {"text": "blush", "qty": 1},
            {"text": "mini applicators", "qty": 1},
        ],
    },

    # -------------------------
    # Bonus / convenience aliases
    # -------------------------
    "go set": {
        "display_name": "TimeWise Miracle Set The Go Set",
        "items": [
            {"text": "TimeWise Miracle Set the go set", "qty": 1},
        ],
    },
    "miracle go set": {
        "display_name": "TimeWise Miracle Set The Go Set",
        "items": [
            {"text": "TimeWise Miracle Set the go set", "qty": 1},
        ],
    },
    "repair go set": {
        "display_name": "TimeWise Repair Volu-Firm The Go Set",
        "items": [
            {"text": "TimeWise Repair Volu-Firm the go set", "qty": 1},
        ],
    },
}


# Optional flat alias helper if you want looser lookup later.
# Right now it's just a convenience index.
ALIASES = {k.lower(): v for k, v in SHORTCUT_SETS.items()}