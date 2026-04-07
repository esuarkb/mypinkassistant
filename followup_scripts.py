# followup_scripts.py
#
# All 2+2+2 follow-up message templates.
# Edit copy here freely — no logic changes needed.
#
# Available placeholders:
#   {p} = cleaned product name (e.g. "CC Cream", "True Dimensions Lipstick")
#   {c} = customer first name (used in all windows)
#   {t} = skincare type (e.g. "serum", "cleanser", "skincare routine")
#   {ft} = fragrance type ("perfume" or "cologne")
#
# "first" = first time the consultant has ever texted this customer via MPA
#   → the intro "Hey {name}, It's {consultant}, your Mary Kay girl!" is prepended automatically
#
# "single" = order had one product (or one clear hero product)
# "multi"  = order had multiple products — keep generic, no {p} needed
#
# Windows:
#   2  = 2-day follow-up  (days 1–4 after order)
#   14 = 2-week follow-up (days 10–18 after order)
#   60 = 2-month follow-up (days 50–70 after order)

SCRIPTS = {

    # ── Skincare ──────────────────────────────────────────────────────────────
    # (cleanser, serum, moisturizer, repair, mask, toner, timewise, microderm, etc.)
    "skincare": {
        "single": {
            2:  "Hey {c}, I wanted to check in — how are you enjoying the {t}?",
            14: "Hey {c}, how are you? Just checking in — the trick with a {t} is sticking with it consistently! Week 2-3 is when most people really start noticing a difference! Let me know if you have any questions or need anything!",
            60: "Hey {c}! You're probably getting close to finishing your {p} — want me to get another one on the way before you run out?",
        },
        "multi": {
            2:  "Hey {c}, I wanted to check in — how is your skin feeling so far?",
            14: "Hey {c}, how are you? Just checking in — week 2-3 is when most people really start noticing a difference! How is your skin feeling? Let me know if you have any questions or need anything!",
            60: "Hey {c}! It's been a couple months — are you getting low on anything? I'd love to help you restock!",
        },
    },

    # ── Color ─────────────────────────────────────────────────────────────────
    # (lipstick, gloss, shadow, mascara, blush, bronzer, foundation, concealer, cc cream)
    "color": {
        "single": {
            2:  "Hey {c}, I wanted to check in — how are you loving the {ct}?",
            14: "Hey {c}, how are you? Just checking in on your {ct} — I hope it's become a daily staple! Let me know if you have any questions or need anything!",
            60: "Hey {c}! Running low on the {p} yet? Just say the word and I'll get more headed your way!",
        },
        "multi": {
            2:  "Hey {c}, I wanted to check in — how are you enjoying everything?",
            14: "Hey {c}, how are you? Just checking in — I hope everything is becoming part of your daily routine! Let me know if you have any questions or need anything!",
            60: "Hey {c}! It's been a couple months — are you running low on anything? I'd love to help you restock!",
        },
    },

    # ── Fragrance ─────────────────────────────────────────────────────────────
    # (perfume, cologne, eau de, fragrance, parfum)
    "fragrance": {
        "single": {
            2:  "Hey {c}, I wanted to check in — have you gotten any compliments on your new scent yet?",
            14: "Hey {c}, how are you? Just checking in — I hope your {ft} is becoming your signature scent! Let me know if you have any questions or need anything!",
            60: "Hey {c}! How are you doing on the {p}? Ready for another bottle?",
        },
        "multi": {
            2:  "Hey {c}, I wanted to check in — how are you enjoying everything?",
            14: "Hey {c}, how are you? Just checking in — I hope you're loving everything so far! Let me know if you have any questions or need anything!",
            60: "Hey {c}! It's been a couple months — are you running low on anything? I'd love to help you restock!",
        },
    },

    # ── Body / Hands ──────────────────────────────────────────────────────────
    # (satin hands, satin lips, lotion, body wash, hand cream, foot)
    "body": {
        "single": {
            2:  "Hey {c}, I wanted to check in — how are you enjoying the {p}?",
            14: "Hey {c}, how are you? Just checking in — I hope you're loving your body care! Let me know if you have any questions or need anything!",
            60: "Hey {c}! Getting close to finishing your {p}? Let me know when you're ready for more!",
        },
        "multi": {
            2:  "Hey {c}, I wanted to check in — how are you enjoying everything?",
            14: "Hey {c}, how are you? Just checking in — I hope you're loving everything so far! Let me know if you have any questions or need anything!",
            60: "Hey {c}! Getting close to running out of anything? Let me know when you're ready for more!",
        },
    },

    # ── Sets / Regimens ───────────────────────────────────────────────────────
    # (set, regimen, system, kit, collection, bundle)
    "set": {
        "single": {
            2:  "Hey {c}, I wanted to check in — how is your new {p} treating you?",
            14: "Hey {c}, how are you? Just checking in — the key is morning and night, consistency is everything with a regimen! How are you feeling about it so far? Let me know if you have any questions or need anything!",
            60: "Hey {c}! Two months in — I hope you're seeing amazing results! Ready to restock your {p}?",
        },
        "multi": {
            2:  "Hey {c}, I wanted to check in — how is everything treating you?",
            14: "Hey {c}, how are you? Just checking in — the key is consistency! How are you feeling about everything so far? Let me know if you have any questions or need anything!",
            60: "Hey {c}! Two months in — I hope you're seeing amazing results! Ready to restock anything?",
        },
    },

    # ── Fallback ──────────────────────────────────────────────────────────────
    # (anything that doesn't match a category above)
    "fallback": {
        "single": {
            2:  "Hey {c}, I wanted to check in — how are you liking the {p} so far?",
            14: "Hey {c}, how are you? Just checking in — I hope you're loving everything! Let me know if you have any questions or need anything!",
            60: "Hey {c}! It's been a couple months — are you running low on the {p}? I'd love to help you restock!",
        },
        "multi": {
            2:  "Hey {c}, I wanted to check in — how are you liking everything so far?",
            14: "Hey {c}, how are you? Just checking in — I hope you're loving everything! Let me know if you have any questions or need anything!",
            60: "Hey {c}! It's been a couple months — are you running low on anything? I'd love to help you restock!",
        },
    },

}
