"""All user-facing chat strings, English + Spanish.

Every key must exist in BOTH dicts — the engine picks by consultant language.
Keep command words (add/remove/cancel) in English inside ES strings; the
parsers match on them.
"""

UI_EN = {
    # Which dict this is. Lets helpers that only receive `ui` pick a
    # language-specific asset (e.g. the Spanish edition of a conversion chart
    # PDF) without an identity check against UI_ES. Added 2026-07-27.
    "lang": "en",
    "empty_prompt": "Say something like: “new customer Jane Doe …” or “order for Jane Doe: …”",
    "canceled": "Okay — canceled. Ready for your new customer or order.",

    "cust_submit_intro": "Okay — here's the customer I'm about to submit:",
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "address": "Address",
    "birthday": "Birthday",
    "none": "(none)",
    "cust_confirm_q": "Does that look right? (yes/no)",
    "cust_edit_hint": "If you need to add or edit just add the correct information in chat.",

    "order_intro": "Okay — I have this order for {first} {last}:",
    "estimated_total": "Estimated retail total: {total}",
    "order_confirm_q": "Does that sound right? (yes/no)",
    "cds_finalize_reminder": "\nReminder: after confirming, you will need to finalize this CDS order on InTouch by navigating to <a href=\"https://apps.marykayintouch.com/order-list\" target=\"_blank\">Orders</a> and completing the order.\n",
    "discount_educate": "💡 I couldn't read that discount — I've built the order at full price. Try <strong>add 20% off</strong> or <strong>$5 off</strong> and I'll apply it.",
    "discount_cds_educate": "💡 No discount applied - MyCustomers can currently only enter discounts on My Inventory orders.",
    "discount_over_total": "💡 Discounts cannot be greater than the retail total — no discount applied. You can add the discount again before confirming.",
    "order_discount_line": "• Discount: −{amount}",
    "order_discount_line_pct": "• Discount ({rate}%): −{amount}",
    "order_tax_line": "• Sales tax ({rate}%): {amount}",
    "order_tax_line_saved": "• Sales tax ({rate}% — {name}'s saved rate): {amount}",
    "order_tax_exempt_note": "• No sales tax — {name} is saved as tax-exempt",
    "order_grand_total": "<strong>Order total: {total}</strong>",

    "need_customer_for_order": "I caught the products but not who they're for! Please retype the order with the customer's name in front — like <strong>New order for Jane: CC cream, mascara</strong>.",
    "need_customer_info": "Okay, tell me the customer's name and information.",
    "need_items": "What items should I add to the order?",
    "got_it_ordering_for": "Got it — order for {name}.",
    "no_matches": "No close matches. Try different words (brand, line, or shade helps), say <strong>skip</strong> to skip this item, or <strong>cancel</strong> to start over.",
    "modifier_noted_item_confirm": "Got it — I'll apply that to the order total. First, about this item:",
    "reply_yes_no_qty": "Reply yes, no, skip, or cancel — or add a quantity like 'x2'",
    "order_adjust_hint": "You can also <strong>add</strong> or <strong>remove</strong> a product, or <strong>cancel</strong> to start over.",

    # ✅ Missing keys your code uses:
    "parse_error": "❌ Parse error: {err}",
    "cant_tell": "I'm not quite sure what you meant! Plain requests work best — like <strong>New order for Jane</strong> or <strong>Who has birthdays this month</strong>. Type <strong>Help</strong> for my full cheat sheet.",
    "cust_confirmed": "✅ {first} {last} confirmed. Adding to MyCustomers now.",
    "cust_reject": "No problem — Send the corrected customer info and I'll try again.",
    "order_confirmed": "✅ Order for {first} {last} confirmed. Sending to MyCustomers now.",
    # The order parser can split one spoken product into fragments that both
    # resolve to the same SKU; the x2 must never be silent (weed-garden
    # 2026-08-15 F1 — a qty-2 order landed in InTouch for a 1-unit intent).
    "order_merge_note": "&nbsp;&nbsp;⚠️ That x{qty} combines {fragments} — if you meant just one item, reply <strong>remove one {name}</strong>.",
    # "no" clears pending entirely (engine.py order_confirm branch) — the copy
    # must NOT invite a paste; a post-"no" paste is a cold parse and gets stolen
    # by other intents (weed-garden 2026-08-15, 4 consultants).
    "order_reject": "Okay — I've cleared that order. Send a fresh one like <strong>Order for Jane, product 1, product 2</strong>. (Tip: to fix just one thing, reply <strong>remove [item]</strong> or <strong>add [item]</strong> instead of no.)",
    "order_empty": "Every item in this order was skipped, so nothing was sent to MyCustomers. When you're ready, start a new order for {first} {last} and I'll help match the products.",

    # CDS address gate (PO Box / missing address) — order_confirm 'yes' branch
    "cds_ask_address_pobox": "One more thing — the address I have for {name} is a PO Box, and Mary Kay can't ship CDS orders to a PO Box. What's the full street address? (like: <strong>444 4th St, Anytown, AL 35976</strong>), or type <strong>cancel</strong> if you don't have the address yet.",
    "cds_ask_address_missing": "One more thing — CDS orders ship directly to the customer, and I don't have an address on file for {name}. What's the full street address? (like: <strong>444 4th St, Anytown, AL 35976</strong>), or type <strong>cancel</strong> if you don't have the address yet.",
    "cds_address_still_pobox": "That's still a PO Box — Mary Kay needs a physical street address for CDS delivery. What's the full street address? (like: <strong>444 4th St, Anytown, AL 35976</strong>)",
    "cds_address_parse_fail": "I couldn't read that as a complete address. Please send the street, city, state, and zip together — like: <strong>444 4th St, Anytown, AL 35976</strong> — or type <strong>cancel</strong>.",
    "cds_address_bad_zip": "The zip code I have ({zip}) isn't 5 digits — Mary Kay needs a 5-digit zip code for CDS delivery. Please send the full address again with the correct zip, or type <strong>cancel</strong>.",

    "no_catalog_match": "I couldn't find that product in the catalog. Try rewording it (brand, line, or shade helps), or say <strong>cancel</strong> to start over.",
    "no_customer_found": "I couldn't find {name} in your saved customers. You can type <strong>help</strong> to see things you can do in chat.",
    "no_customer_found_yet": "I couldn't find {name} in your saved customers yet. You can type <strong>help</strong> to see things you can do in chat.",
    # wording deliberately says "matches a customer" rather than asserting
    # identity — an archived record can be the same woman re-added under a
    # new surname (weed-garden 2026-08-16, c124)
    "customer_archived_lookup": "<strong>{name}</strong> matches a customer who's archived in your MyCustomers, so she doesn't show up in searches here. If you'd like her back, unarchive her in MyCustomers and she'll come into MyPinkAssistant on the next sync — order history and all.",
    "no_customer_id": "I couldn't find a customer with ID {cid}.",
    "customer_spent": "{name} has spent ${total} ({period}).",
    "who_is_customer": "Who is the customer? Try: \u201cshow Jane\u2019s info\u201d.",
    "multiple_matches": "Multiple matches: Reply with 1, 2, or 3 — or type cancel.",
    "lost_order_draft": "I lost track of that order draft. Please paste the order again.",
    "what_to_do_customer": "Okay — what would you like to do with that customer?",
    "inventory_added": "Added {qty} of {product} to your inventory. You currently have {current} on hand.",
    "inventory_removed": "Removed {qty} of {product} from your inventory. You currently have {current} on hand.",
    "inventory_set": "Set {product} inventory to {qty}. You currently have {current} on hand.",
    "inventory_report": "Here's your inventory report: {link}",
    "reply_yes_no": "Reply yes or no.",
    "pick_match_5": "Pick the best match with 1-5, or type cancel.",
    "low_stock_set": "Got it — I'll flag {product} when you have fewer than {qty} on hand.",
    "confirming_customer": "You're confirming a new customer. Reply yes or no, or type cancel to retry.",
    "deleted_customer": "✅ Deleted {name} from MyPinkAssistant (MyCustomers was not changed).",
    "delete_failed": "I couldn't delete that customer (maybe it was already removed).",
    "delete_confirm_prompt": "To confirm deletion, type DELETE. Or type <strong>cancel</strong>.",
    "no_items_caught": "I didn't catch any items — try again with the product names.",
    "add_hint": "Tell me what to add, e.g. `add satin hands`.",
    "remove_hint": "Tell me what to remove, e.g. `remove 1` or `remove charcoal`.",
    "remove_not_found": "I couldn't find that item to remove. Try `remove 1` or part of the name.",
    "confirming_order": "You're confirming an order. Reply <strong>yes</strong> or <strong>no</strong>, or say <strong>add [product]</strong> or <strong>remove [product]</strong> to edit the order.",
    "reply_yes_no_adjust": "Reply <strong>yes</strong>, <strong>no</strong>, or <strong>cancel</strong>, or tell me to <strong>add [product]</strong> or <strong>remove [product]</strong>.",
    "trouble": "I'm having a little trouble right now, please try again in a moment.",
    "customer_not_in_mc": "I'm not finding {name} in MyCustomers. We will need to add {name} as a new customer first.",
    "propose_top": "I think you mean: {line}. Is that right? (yes/no)",
    "render_top5_intro": "Got it \u2014 select the best match (reply {range}), or type different search words and I'll search again:",

    "submitted_order_edit": "Once an order has been sent to MyCustomers I can't currently edit or remove it from chat. You can delete or change the order in <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>, and MyPinkAssistant will get the corrected info on the next sync.",
    "submitted_order_add": "Heads up: we can't currently add to orders already submitted to MyCustomers. If you add the item to the order in <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>, it will be added to MyPinkAssistant on the next sync.",

    "pcp_enroll": "Adding or removing customers on PCP is done on Mary Kay InTouch — see your <a href=\"https://apps.marykayintouch.com/enrolled-preferred-customers\" target=\"_blank\">Preferred Customer Program</a> page. Your enrolled list shows up here automatically after each quarterly update — say <strong>show my PCP list</strong> to see it.",

    "stray_digit": "That numbered list has already been answered, so a number by itself doesn't point to anything right now. Just ask again and I'll show you fresh choices.",

    "notes_educate": "We are working on the ability to add notes to customers. Currently you can log into <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a> to add or edit notes.",
    "mycustomers_link": "Here's the link to <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>&nbsp; <button class=\"fdp-copy copy-link-btn\" data-copy=\"https://apps.marykayintouch.com/customer-list\">Copy Link</button>",
    "bulk_text_educate": "I can't send texts directly to customers, but if you say <strong>Do I have any followups</strong> you can click the tap-to-text button to text a followup message directly from your phone.",

    # Migrated from hardcoded engine/render strings 2026-07-06 (bundle E slice) —
    # EN text byte-identical to the originals
    "app_help": (
        "<strong>Add MPA to your home screen</strong>\n\n"
        "<strong>iPhone / iPad (Safari):</strong>\n"
        "1. Tap the <strong>Share</strong> button (box with arrow) at the bottom of the screen\n"
        "2. Scroll down and tap <strong>Add to Home Screen</strong>\n"
        "3. Tap <strong>Add</strong> — done!\n\n"
        "<strong>Android (Chrome):</strong>\n"
        "1. Tap the <strong>⋮ menu</strong> in the top-right corner\n"
        "2. Tap <strong>Add to Home Screen</strong> or <strong>Install App</strong>\n"
        "3. Tap <strong>Add</strong> — done!\n\n"
        "Once installed it opens full-screen with no browser bar, just like a real app."
    ),
    "inventory_help": (
        "Here are a few inventory things you can say:\n"
        "\n"
        "📦 View & update quantities:\n"
        "• show my inventory\n"
        "• how many charcoal masks do I have\n"
        "• add 3 satin hands to inventory\n"
        "• remove 1 charcoal mask from inventory\n"
        "• set satin hands inventory to 5\n"
        "\n"
        "🎯 Set a desired quantity (your 'always keep on hand' level):\n"
        "• set charcoal mask par to 3\n"
        "\n"
        "📋 Check what to reorder:\n"
        "• what am I low on\n"
        "• what should I order\n"
        "\n"
        "🖨️ Print your inventory:\n"
        "• print my inventory"
    ),

    # Feature-help bubbles (2026-07-06, Brian-approved copy)
    "order_help": "<strong>Ordering in chat:</strong> just say the customer and what she wants — like <em>\"Order for Jane Doe, charcoal mask x2 and satin lips set.\"</em><br>I'll match each item and you confirm with <strong>yes</strong>, <strong>no</strong>, or <strong>skip</strong>. When you approve the order, I enter it in MyCustomers for you automatically.<br>Shipping straight to her? Start with <em>\"CDS order for Jane Doe…\"</em> — I'll build the order in MyCustomers and <strong>leave it pending</strong>, so you can pop in, add samples, and submit it for processing when it's just right.",
    "followup_names_missing": "Couldn't find in your customers: {names}",
    "followup_help": "<strong>Follow-ups (2+2+2):</strong> I track who bought recently and remind you to check in — 2 days, 2 weeks, and 2 months after each order, the Mary Kay way.<br>Say <strong>follow ups</strong> and I'll show cards for everyone who's due, each with a <strong>tap-to-text</strong> button that opens a ready-to-send message right from your phone.",
    "sync_help": "<strong>How syncing works:</strong> customers and orders you enter here go <strong>to</strong> MyCustomers within a couple of minutes.<br>Changes made <strong>in</strong> MyCustomers (edits, orders placed there, your team reports) come back to me overnight, every night.<br>So if something looks out of date today, it almost always catches up by tomorrow morning.",
    "billing_help": "<strong>Your subscription:</strong> $5.99/month, every feature included, cancel anytime — no contracts, no tiers.<br>Manage or cancel from the <a href='/settings'>Settings page</a>.<br>Love MPA? Say <strong>referral link</strong> — friends you refer get a 30-day free trial, and you get a free month when they subscribe. 💗",
    "privacy_help": "<strong>Your data:</strong> your customer records, order history, and team reports live on our secure servers and are visible only to you — never sold, never shared, never used to train AI.<br>The AI reads your chat messages to understand what you're asking, but your stored records and your InTouch login (which is encrypted) never leave our servers.<br>Questions? Email <a href='mailto:support@mypinkassistant.com'>support@mypinkassistant.com</a>.",

    # Unit / team query strings
    "unit_no_data": "I don't have team data synced for your account yet. Once a report sync runs, I'll be able to answer questions about your team.",
    "unit_query_rephrase": "I had trouble generating a query. Please try rephrasing your question.",
    "unit_query_unclear": "I wasn't able to form a query for that. Try rephrasing \u2014 for example, 'who has MyShop set up' or 'show me inactive consultants'.",
    "unit_read_only": "I can only read data, not modify it. Please ask a question about your team.",
    "unit_unsafe_query": "That query isn't something I can run safely. Please ask a read-only question.",
    "unit_query_error": "I wasn't able to pull that report right now. Try rephrasing, or ask something like 'who doesn't have MyShop set up' or 'who is close to a Great Start bundle'.",
    "data_query_rephrase": "I had trouble forming a query for that. Try rephrasing — for example, 'who ordered in May' or 'how many orders last month'.",
    "data_query_error": "I wasn't able to run that search right now. Try rephrasing your question.",
    "data_query_no_results": "No results found for that search.",
    "unit_member_not_found": "I couldn't find a team member named {name}.",
    "unit_no_results": "No consultants match that criteria.",
    "unit_consultant_count": "{n} consultant (as of the latest sync):",
    "unit_consultants_count": "{n} consultants (as of the latest sync):",

    # unit_query.py result-formatting strings (bundle E, 2026-07-11)
    "unit_query_result_count_fallback": "{n} result(s) found.",
    "unit_query_count_consultant": "{count} consultant",
    "unit_query_count_consultants": "{count} consultants",
    "unit_query_count_result": "{count} result",
    "unit_query_count_results": "{count} results",
    "unit_query_unknown_name": "Unknown",
    "unit_query_ends_date": "ends {month} {day}",
    "unit_query_ends_date_fallback": "ends {date}",
    "unit_query_contest_amount": "{amount} this quarter",
    "unit_query_needed_next_bundle": "{amount} to next bundle",
    "unit_query_needed_level": "{amount} to {level}",
    "unit_query_needed_next_level_generic": "{amount} to next level",
    "unit_query_month_achieved": "{count} month achieved",
    "unit_query_months_achieved": "{count} months achieved",
    "unit_query_amount_needed_qualify": "{amount} to qualify this month",
    "unit_query_myshop_status": "MyShop: {mark}",

    # car_program.py strings (bundle E, 2026-07-11)
    "car_program_no_data": "I don't have any car program data on file yet. Run a report sync first (this happens automatically each night) and try again.",
    "car_program_header": "Car Program — {level} (as of the latest sync)\n",
    "car_program_status": "Status: {status_desc}",
    "car_program_current_quarter": "current quarter",
    "car_program_production_of_goal": "{qtr_label} production: {q0} of {maint_min}",
    "car_program_remaining": "Remaining: {short} this quarter",
    "car_program_goal_met": "Goal met ✓",
    "car_program_production_only": "{qtr_label} production: {q0}",
    "car_program_on_target_goal": "On-target goal: {ot_goal}  (need {needed_ot} more)",
    "car_program_last_quarter": "Last quarter: {q1}",
    "car_program_two_quarters_ago": "Two quarters ago: {q2}",
    "car_program_copay_amount": "Co-pay: {copay}/mo this quarter",
    "car_program_copay_none": "Co-pay: None ✓",
    "car_program_requal_date": "Requalification Date: {date}",
    "car_program_no_award": "None",
    "car_program_status_unknown": "Unknown",

    # render.py picker/list strings (bundle E, 2026-07-11)
    "render_customer_single_intro": "Is this who you mean?",
    "render_customer_multi_intro": "I found multiple customer matches — reply with 1-{n}:",
    "render_delete_picker_intro": "I found multiple matches. Reply with 1{suffix} to choose which customer to delete:",
    "render_delete_orders_label": "Orders:",
    "render_delete_no_orders": "none",
    "render_delete_birthday": "Birthday: {birthday}",
    "render_top5_intro_skip": "Got it — select the best match, try different search words, or say <strong>skip</strong> to move on.",
    "inventory_list_intro": "Here is your current inventory:",
    "inventory_list_empty": "Your inventory is empty.",
    "inventory_list_none_shown": "We have not yet added any items to your inventory.",
    "inventory_row_with_price": "• {name} {price} — {qty} on hand",
    "inventory_row_no_price": "• {name} — {qty} on hand",
    "inventory_item_present": "You have {qty} {name} in inventory.",
    "inventory_item_absent": "You have 0 {name} in inventory.",
    "low_stock_intro": "Here's what you need to reorder:",
    "low_stock_none": "You're all stocked up — nothing is below your desired on-hand levels.",
    "low_stock_row": "• {name} — you have {qty}, want {threshold} (need {needed} more)",
    "low_stock_unknown_product": "Unknown product",
    "propose_top_no_match": "I couldn't find {label} in the catalog. Try rewording it (brand, line, or shade helps), say <strong>skip</strong> to skip this item, or <strong>cancel</strong> to start over.",
    "propose_top_no_match_default_label": "that product",

    # chat_help cheat-sheet (moved verbatim from render.py's _build_chat_help_html
    # 2026-07-11; text unchanged, just relocated so it lives with the rest of
    # the UI strings)
    "chat_help_base": "<strong>Here are some things you can do in chat:</strong>\n\n<strong>Customers</strong>\n• Look up a customer — just type their name: <em>Jane Doe</em>\n• Add a customer — <em>New customer Jane Doe, 555-1234, jane@gmail.com</em>\n• What someone ordered — <em>What did Jane order</em>\n\n<strong>Orders</strong>\n• Place an order — <em>Order for Jane: 2 lipsticks and a foundation</em>\n• Look up a product & price — <em>Satin hands</em> or <em>How much is the charcoal mask</em>\n\n<strong>Your customers</strong>\n• By city — <em>Customers in Huntsville</em>\n• Lapsed — <em>Who hasn't ordered in 3 months</em>\n• Top spenders — <em>Who are my top customers</em>\n• Birthdays — <em>Who has birthdays this month</em>\n\n<strong>Inventory</strong>\n• Check stock — <em>How many TimeWise moisturizers do I have</em>\n• Set a par — <em>Set charcoal mask par to 3</em>\n\n<strong>Other</strong>\n• Current Look Book — <em>Look book</em>\n• Order of Application chart — <em>Order of application</em>\n• Shade conversion charts — <em>Conversion chart</em>\n• Your referral link — <em>My referral link</em>",
    "chat_help_team_extra": "\n\n<strong>Your team</strong>\n• <em>Who is on my team</em>\n• <em>Who hasn't set up MyShop</em>\n• <em>Who is close to a Great Start bundle</em>\n• <em>Who is on Sarah's team</em>",

    # catalog.py product-lookup strings (bundle E, 2026-07-11)
    "product_lookup_header": "Product Look Up",
    "product_fact_sheet_link": "Product Fact Sheet",
    "product_order_of_application_link": "Order of Application",
    "order_of_application_reply": 'Here\'s the <a href="{url}" target="_blank">Order of Application chart</a>&nbsp; <button class="fdp-copy copy-link-btn" data-copy="{url}">Copy Link</button>',

    # Shade conversion charts (2026-07-27). MK-hosted PDFs, target="_blank" like
    # the OOA chart. Labels are MK's own document titles so consultants recognize
    # them; note MK titles the powder one "Chart", not "Conversion Chart".
    "conversion_chart_header": "<strong>Shade conversion charts</strong>",
    "conversion_chart_row": '• <a href="{url}" target="_blank">{label}</a>',
    "conversion_chart_single": 'Here\'s the <a href="{url}" target="_blank">{label}</a>',
    "conversion_chart_more": "\n\nSay <em>conversion charts</em> to see them all.",
    "conversion_chart_label_foundation": "TimeWise 3D Foundation — New Shade Conversions",
    "conversion_chart_label_concealer": "Concealer Shade Conversion",
    "conversion_chart_label_powder": "Silky Setting Powder Chart",
    "conversion_chart_label_lip_liner": "Waterproof Lip Liner Conversion Chart",
    "conversion_chart_label_range": "TimeWise 3D Foundations Range and Category Chart",
    "product_conversion_chart_link": "Shade Conversion Chart",
    "sales_tax_set": "✅ Sales tax rate set to <strong>{rate}%</strong>. I'll add it to your My Inventory orders from now on — say <strong>no tax</strong> on an order to skip it, or set the rate to 0 to turn it off.",
    "sales_tax_cleared": "✅ Sales tax turned off. Your orders will not include tax.",
    "sales_tax_show": "Your sales tax rate is <strong>{rate}%</strong>. Say <em>set my sales tax to 7.5%</em> to change it, or set it to 0 to turn it off.",
    "sales_tax_unset": "You don't have a sales tax rate set, so orders don't include tax. Say <em>set my sales tax to 7.5%</em> and I'll add it to your My Inventory orders automatically.",
    "sales_tax_invalid": "I couldn't read that rate. Try <em>set my sales tax to 7.5%</em> (0–100).",
    "customer_tax_save_prompt": "💡 Want me to save <strong>{rate}%</strong> as {name}'s tax rate for future orders? Reply <strong>yes</strong> to save it.",
    "customer_tax_save_prompt_exempt": "💡 Want me to save {name} as <strong>tax-exempt</strong> so future orders skip sales tax? Reply <strong>yes</strong> to save it.",
    "customer_tax_saved": "✅ Saved! {name}'s orders will use <strong>{rate}%</strong> sales tax from now on.",
    "customer_tax_saved_exempt": "✅ Saved! {name} is marked tax-exempt — no sales tax on their orders.",
    "customer_tax_set": "✅ {name}'s tax rate set to <strong>{rate}%</strong>. Their orders will use it automatically.",
    "customer_tax_cleared": "✅ Cleared {name}'s saved tax rate. Their orders go back to your default rate.",
    "customer_tax_show": "{name}'s saved tax rate is <strong>{rate}%</strong>. Say <em>set {name}'s tax rate to 5.5%</em> to change it, or <em>clear {name}'s tax rate</em> to remove it.",
    "customer_tax_show_exempt": "{name} is saved as <strong>tax-exempt</strong> — no sales tax on their orders. Say <em>clear {name}'s tax rate</em> to undo that.",
    "customer_tax_unset": "{name} doesn't have a saved tax rate — orders use your default rate. Say <em>set {name}'s tax rate to 5.5%</em> to save one.",
    "customer_tax_save_declined": "👍 Okay — I won't save it.",
    "customer_tax_ambiguous": "I found more than one customer matching {name} — try again with their full name, like <em>set Jane Smith's tax rate to 5.5%</em>.",
    "inventory_category_header": "<strong>{label} in stock</strong> — {total} on hand:",
    "inventory_category_empty": "You don't have any {label} items in your inventory right now.",
    "product_history_header": "<strong>{name}'s {filter}:</strong>",
    "product_history_none": "I don't see any {filter} in {name}'s order history.",
    "product_part_number": "Part # {sku}",
    "product_lookup_not_found_bullet": "• I couldn't find \"{name}\"",

    # inventory_guardrail (bundle E, 2026-07-11)
    "inventory_guardrail": (
        "That looks like an inventory update.\n"
        "Try again using the word 'inventory':\n"
        "• add 3 satin hands to inventory\n"
        "• remove 1 satin hands from inventory\n"
        "• set satin hands inventory to 5"
    ),

    # Inline engine.py reply strings migrated 2026-08-17 (Spanish-parity pass;
    # trigger: c140 chose Español at signup and would have hit English prompts).
    # EN text byte-identical to the originals, with two exceptions: the two
    # "no email for the/an invoice" variants unified on one wording, and the
    # order-line catalog-miss sites now reuse propose_top_no_match.
    # ES command words: cancel/skip have recognized Spanish forms ("cancelar",
    # "omitir" — intent_router.py:1382, render.py:61) so ES copy uses those;
    # everything else (DELETE, invoice Jane Smith, inventory examples) stays
    # English because the parsers only match English.

    # product/category browsing
    "category_big_list_hint": "That's a lot to list — here it is by type (tap one):",
    "category_product_count": "{n} products",
    "more_products_link": "+{n} more",
    "product_search_no_matches": "I couldn't find any products matching that search.",
    "product_not_found_try_different": "I couldn't find that product in the catalog. Try a different name or part of the name.",
    "product_one_at_a_time": "I can look up one product at a time — try searching for each one separately.",
    "look_book_line": 'Here\'s the <a href="{url}" class="inapp-overlay-link">{label}</a>&nbsp; <button class="fdp-copy copy-link-btn" data-copy="{url}">Copy Link</button>',
    "inventory_no_thresholds": "You haven't set any desired on-hand levels yet.\nTry: \"keep 3 charcoal mask on hand\" and I'll track that for you.",

    # delete customer confirms (DELETE stays English — deliberate friction;
    # the handler also accepts "cancelar" as of this pass)
    "delete_customer_confirm_orders": "This will delete {name} from MyPinkAssistant and also remove {count} local order(s). Type DELETE to confirm, or `cancel`.",
    "delete_customer_confirm_plain": "This will delete {name} from MyPinkAssistant. Type DELETE to confirm, or <strong>cancel</strong>.",

    # customer edit redirect
    "edit_request_redirect": 'Changes or updates to customer information must currently be done from <a href="https://apps.marykayintouch.com/customer-list" target="_blank">MyCustomers</a>. The changes will then show in MyPinkAssistant on the next sync.',

    # customer-vs-consultant disambiguation picker (engine-built rows)
    "picker_found_options": "I found these options — which did you mean?",
    "picker_multiple_matches": "I found multiple matches — reply with 1 or {total}:",
    "picker_label_customer": "Customer",
    "picker_label_consultant": "Consultant",

    # invoices (2026-08-04 feature). invoice_sent must stay PLAIN text —
    # app.js only switches a bubble to innerHTML on "<a ", "<div", "<strong".
    # "Send invoice" is the literal button label (crm_store.py) — same for
    # both languages until that button is translated.
    "invoice_how": "To send an invoice, pull up the customer's orders and tap <strong>Send invoice</strong> on the one you want.",
    "invoice_no_email_sync": "I don't have an email address for {name}, so there's nowhere to send the invoice. Add her email in MyCustomers and it'll sync over.",
    "invoice_who": "Who is the invoice for? Say something like <strong>invoice Jane Smith</strong> and I'll show you her orders.",
    "invoice_no_orders": "I don't see any orders for {name} to invoice.",
    "invoice_which_order": "Which order?",
    "invoice_order_not_found": "I couldn't find that order.",
    "invoice_no_email_short": "I don't have an email address for {name}.",
    "invoice_cds_blocked": "That one shipped from Mary Kay directly, so they already billed your customer for it — there's no invoice to send.",
    "invoice_unpriced_blocked": "I can't send that one — I don't have a price on file for everything on it, so your customer would see an item as free. Nightly sync usually fills those in.",
    "invoice_send_failed": "I couldn't send that invoice just now. Give it a minute and try again — if it keeps failing, email support@mypinkassistant.com.",
    "invoice_sent": "✅ Invoice sent to {name} at {email}.",

    # PCP list
    "pcp_none": "No PCP customers found for the current quarter.",
    "pcp_header": "<strong>PCP List</strong> ({remaining} remaining · {total} total)",

    # top sellers + shared period labels (birthdays reuse the overlapping ones)
    "top_sellers_none": "No order history found for {label}.",
    "top_sellers_header": "<strong>Your Top Sellers</strong> ({label})",
    "top_sellers_row": "{i}. {name} — {qty} units",
    "period_this_month": "this month",
    "period_this_quarter": "this quarter",
    "period_this_year": "this year",
    "period_all_time": "all time",
    "period_last_12_months": "the last 12 months",
    "period_today": "today",
    "period_tomorrow": "tomorrow",
    "period_this_week": "this week",
    "period_next_week": "next week",
    "period_next_month": "next month",
    "period_next_30_days": "the next 30 days",

    # birthdays. bday_header: EN reads "Customer Birthdays This Month" (scope
    # prefixes the noun); ES reads "Cumpleaños de clientas este mes" (scope
    # follows it) — the {scope} slot position differs by design.
    "bday_in_month": "in {month}",
    "month_names": "January,February,March,April,May,June,July,August,September,October,November,December",
    "bday_none": "No {who} with birthdays {period}.",
    "bday_who_customers": "customers",
    "bday_who_consultants": "consultants",
    "bday_who_both": "customers or consultants",
    "bday_header": "<strong>{scope}Birthdays {period}</strong>",
    "bday_scope_customers": "Customer ",
    "bday_scope_consultants": "Consultant ",
    "bday_scope_both": "",

    # lapsed customers ("show all" expansion)
    "lapsed_no_more": "No additional lapsed customers beyond the top 5.",
    "lapsed_all_header": "All lapsed customers ({period}+):",
    "unit_month": "month",
    "unit_months": "months",
    "unit_days": "days",
    "months_ago": "{n} months ago",
    "days_ago": "{n} days ago",

    # customers-by-city coaching (example commands stay English — the router
    # matches "customers in ...")
    "city_lookup_hint": "This looks like a city/state lookup. Try \"customers in Madison\" or \"customers in Madison, WI\"",

    # new-customer confirm validation gauntlet (each returns with pending kept
    # open so the corrected value applies as an edit via customer_edits)
    "cust_need_full_name": "I need both a first and last name before MyCustomers can save this customer. Please type <strong>cancel</strong> and re-enter the customer with the full name.",
    "cust_bad_phone": "The phone number I have ({phone}) isn't 10 digits — MyCustomers requires a 10-digit US number. Please type the correct number or say cancel.",
    "cust_partial_address": "I only see a partial address. Please enter the full address (street, city, state, and zip) — or say “no address” to save this customer without one.",
    "cust_bad_state": "I wasn't able to recognize \"{state}\" as a valid state. Please re-enter the address with the full state name (e.g. Texas) or abbreviation (e.g. TX), or say cancel.",
    "cust_bad_zip": "The zip code I have ({zip}) doesn't look right — MyCustomers requires a 5-digit zip code (or ZIP+4 like 12345-6789). Please type the correct zip code or say cancel.",
    "cust_email_space": "The email I have ({email}) has a space in it — please type it again without the space, or say cancel.",
    "cust_email_invalid": "The email I have ({email}) doesn't look valid — please type the correct email or say cancel.",
    "cust_future_birthday": "The birthday I have ({birthday}) is in the future — please type the correct birthday or say cancel.",

    # awaiting_order_items guard
    "add_item_prompt": "I don't see an item I can add to {first} {last}'s order. You can type what you would like to add to the order or say cancel to start over.",

    # customer_edits.py confirmation notes ("Updated: Email updated, …")
    "edit_notes_prefix": "Updated: ",
    "edit_note_email": "Email updated",
    "edit_note_phone": "Phone updated",
    "edit_note_birthday": "Birthday updated",
    "edit_note_referred_by": "Referred By updated",
    "edit_note_tags": "Tags updated",
    "edit_note_address": "Address updated",
    "edit_note_address_street": "Address updated (street)",
    "edit_note_zip": "Postal code updated",
    "edit_note_address_removed": "Address removed — will save without one",
    "edit_note_failed": "Couldn't apply: “{raw}”",
}

UI_ES = {
    "lang": "es",
    "empty_prompt": "Di algo como: “nuevo cliente Jane Doe …” o “pedido para Jane Doe: …”",
    "canceled": "Listo — cancelado. Estoy listo para tu nuevo cliente o pedido.",

    "cust_submit_intro": "Perfecto — este es el cliente que estoy por enviar:",
    "name": "Nombre",
    "email": "Correo",
    "phone": "Teléfono",
    "address": "Dirección",
    "birthday": "Cumpleaños",
    "none": "(ninguno)",
    "cust_confirm_q": "¿Se ve correcto? (sí/no)",
    # keep add/edit commands in English so your parser stays simple
    "cust_edit_hint": "Si necesitas agregar o editar, escribe la información correcta en el chat.",

    "order_intro": "Perfecto — tengo este pedido para {first} {last}:",
    "estimated_total": "Total estimado (precio): {total}",
    "order_confirm_q": "¿Suena bien? (sí/no)",
    "cds_finalize_reminder": "\nRecordatorio: después de confirmar, deberás finalizar este pedido CDS en InTouch entrando a <a href=\"https://apps.marykayintouch.com/order-list\" target=\"_blank\">Pedidos</a> (Orders) y completando el pedido.\n",
    "discount_educate": "💡 No pude leer ese descuento — armé el pedido a precio completo. Intenta <strong>agregar 20% de descuento</strong> o <strong>$5 de descuento</strong> y lo aplicaré.",
    "discount_cds_educate": "💡 No se aplicó ningún descuento - MyCustomers actualmente solo permite ingresar descuentos en pedidos de My Inventory.",
    "discount_over_total": "💡 Los descuentos no pueden ser mayores que el total de venta — no se aplicó ningún descuento. Puedes agregar el descuento de nuevo antes de confirmar.",
    "order_discount_line": "• Descuento: −{amount}",
    "order_discount_line_pct": "• Descuento ({rate}%): −{amount}",
    "order_tax_line": "• Impuesto de ventas ({rate}%): {amount}",
    "order_tax_line_saved": "• Impuesto de ventas ({rate}% — tasa guardada de {name}): {amount}",
    "order_tax_exempt_note": "• Sin impuesto de ventas — {name} tiene guardada la exención de impuestos",
    "order_grand_total": "<strong>Total del pedido: {total}</strong>",

    "need_customer_for_order": "Entendí los productos, ¡pero no para quién son! Vuelve a escribir el pedido con el nombre del cliente al frente — como <strong>New order for Jane: CC cream, mascara</strong>.",
    "need_customer_info": "Perfecto, dime el nombre del cliente y su información.",
    "need_items": "¿Qué artículos debo agregar al pedido?",
    "got_it_ordering_for": "Listo — pedido para {name}.",
    "no_matches": "No encontré coincidencias cercanas. Prueba con otras palabras (marca, línea o tono ayuda), escribe <strong>skip</strong> para omitir este artículo, o <strong>cancel</strong> para empezar de nuevo.",
    "modifier_noted_item_confirm": "Anotado — lo aplicaré al total del pedido. Primero, sobre este artículo:",
    "reply_yes_no_qty": "Responde sí/no — o escribe una cantidad como `2` o `x2`.",
    "order_adjust_hint": "También puedes <strong>add</strong> o <strong>remove</strong> un producto, o <strong>cancel</strong> para empezar de nuevo.",

    # ✅ Missing keys your code uses:
    "parse_error": "❌ Error al interpretar: {err}",
    "cant_tell": "No entendí muy bien lo que quisiste decir. Las solicitudes sencillas funcionan mejor — como <strong>New order for Jane</strong> o <strong>Who has birthdays this month</strong>. Escribe <strong>Help</strong> para ver mi guía completa.",
    "cust_confirmed": "✅ {first} {last} confirmado. Agregando a MyCustomers ahora.",
    "cust_reject": "No hay problema — envíame la info corregida del cliente y lo intento de nuevo.",
    "order_confirmed": "✅ Pedido para {first} {last} confirmado. Enviándolo a MyCustomers ahora.",
    "order_merge_note": "&nbsp;&nbsp;⚠️ Ese x{qty} combina {fragments} — si era un solo producto, responde <strong>remove one {name}</strong>.",
    "order_reject": "Listo — borré ese pedido. Envía uno nuevo como <strong>Order for Jane, producto 1, producto 2</strong>. (Consejo: para corregir solo una cosa, responde <strong>remove [producto]</strong> o <strong>add [producto]</strong> en vez de no.)",
    "order_empty": "Todos los artículos de este pedido fueron omitidos, así que no se envió nada a MyCustomers. Cuando estés lista, empieza un nuevo pedido para {first} {last} y te ayudo a encontrar los productos.",

    # CDS address gate (PO Box / missing address) — order_confirm 'yes' branch
    "cds_ask_address_pobox": "Una cosa más — la dirección que tengo para {name} es un apartado postal (PO Box), y Mary Kay no puede enviar pedidos CDS a un PO Box. ¿Cuál es la dirección física completa? (como: <strong>444 4th St, Anytown, AL 35976</strong>), o escribe <strong>cancelar</strong> si aún no tienes la dirección.",
    "cds_ask_address_missing": "Una cosa más — los pedidos CDS se envían directamente al cliente, y no tengo una dirección registrada para {name}. ¿Cuál es la dirección física completa? (como: <strong>444 4th St, Anytown, AL 35976</strong>), o escribe <strong>cancelar</strong> si aún no tienes la dirección.",
    "cds_address_still_pobox": "Eso sigue siendo un apartado postal (PO Box) — Mary Kay necesita una dirección física para la entrega CDS. ¿Cuál es la dirección física completa? (como: <strong>444 4th St, Anytown, AL 35976</strong>)",
    "cds_address_parse_fail": "No pude leer eso como una dirección completa. Envía la calle, ciudad, estado y código postal juntos — como: <strong>444 4th St, Anytown, AL 35976</strong> — o escribe <strong>cancelar</strong>.",
    "cds_address_bad_zip": "El código postal que tengo ({zip}) no tiene 5 dígitos — Mary Kay necesita un código postal de 5 dígitos para la entrega CDS. Envía la dirección completa de nuevo con el código postal correcto, o escribe <strong>cancelar</strong>.",

    "no_catalog_match": "No pude encontrar ese producto en el catálogo. Intenta describirlo de otra forma (marca, línea o tono ayuda), o di `cancelar` para empezar de nuevo.",
    "no_customer_found": "No encontré a {name} en tus clientes guardados. Puedes escribir <strong>ayuda</strong> para ver lo que puedes hacer en el chat.",
    "no_customer_found_yet": "Aún no encontré a {name} en tus clientes guardados. Puedes escribir <strong>ayuda</strong> para ver lo que puedes hacer en el chat.",
    "customer_archived_lookup": "<strong>{name}</strong> coincide con una clienta archivada en tu MyCustomers, por eso no aparece en las búsquedas aquí. Si quieres recuperarla, desarchívala en MyCustomers y volverá a MyPinkAssistant en la próxima sincronización — con todo su historial de pedidos.",
    "no_customer_id": "No encontré un cliente con ID {cid}.",
    "customer_spent": "{name} ha gastado ${total} ({period}).",
    "who_is_customer": "¿Quién es el cliente? Prueba: \u201cinfo de Jane\u201d.",
    "multiple_matches": "Varias coincidencias: responde con 1, 2 o 3 — o escribe cancelar.",
    "lost_order_draft": "Perdí el borrador del pedido. Por favor, vuelve a pegar el pedido.",
    "what_to_do_customer": "Listo — ¿qué quieres hacer con ese cliente?",
    "inventory_added": "Agregué {qty} de {product} a tu inventario. Actualmente tienes {current} disponibles.",
    "inventory_removed": "Eliminé {qty} de {product} de tu inventario. Actualmente tienes {current} disponibles.",
    "inventory_set": "Actualicé el inventario de {product} a {qty}. Actualmente tienes {current} disponibles.",
    "inventory_report": "Aquí está tu reporte de inventario: {link}",
    "reply_yes_no": "Responde sí o no.",
    "pick_match_5": "Elige la mejor opción del 1 al 5, o escribe cancelar.",
    "low_stock_set": "Listo — te avisaré sobre {product} cuando tengas menos de {qty} disponibles.",
    "confirming_customer": "Estás confirmando un nuevo cliente. Responde sí o no, o escribe cancelar para reintentar.",
    "deleted_customer": "✅ {name} eliminado de MyPinkAssistant (MyCustomers no fue modificado).",
    "delete_failed": "No pude eliminar ese cliente (quizás ya fue removido).",
    "delete_confirm_prompt": "Para confirmar la eliminación, escribe ELIMINAR. O escribe `cancelar`.",
    "no_items_caught": "No detecté ningún artículo — intenta de nuevo con los nombres de los productos.",
    "add_hint": "Dime qué agregar, por ejemplo: `add satin hands`.",
    "remove_hint": "Dime qué eliminar, por ejemplo: `remove 1` o `remove charcoal`.",
    "remove_not_found": "No encontré ese artículo para eliminarlo. Prueba `remove 1` o parte del nombre.",
    "confirming_order": "Estás confirmando un pedido. Responde sí o no, o di agregar o eliminar para editarlo.",
    "reply_yes_no_adjust": "Responde sí o no — o di agregar o eliminar para ajustar el pedido.",
    "trouble": "Estoy teniendo un pequeño problema ahora mismo, por favor intenta de nuevo en un momento.",
    "customer_not_in_mc": "No encuentro a {name} en MyCustomers. Necesitaremos agregar a {name} como nueva cliente primero.",
    "propose_top": "Creo que te refieres a: {line}. ¿Es correcto? (sí/no)",

    "submitted_order_edit": "Una vez que un pedido se envió a MyCustomers, por el momento no puedo editarlo ni eliminarlo desde el chat. Puedes eliminar o cambiar el pedido en <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>, y MyPinkAssistant recibirá la información corregida en la próxima sincronización.",
    "submitted_order_add": "Aviso: por el momento no podemos agregar artículos a pedidos ya enviados a MyCustomers. Si agregas el artículo al pedido en <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>, se agregará a MyPinkAssistant en la próxima sincronización.",

    "pcp_enroll": "Agregar o quitar clientas del PCP se hace en Mary Kay InTouch — visita tu página del <a href=\"https://apps.marykayintouch.com/enrolled-preferred-customers\" target=\"_blank\">Programa de Clientas Preferidas</a>. Tu lista inscrita aparece aquí automáticamente después de cada actualización trimestral — di <strong>muestra mi lista PCP</strong> para verla.",

    "stray_digit": "Esa lista numerada ya fue respondida, así que un número por sí solo no señala nada en este momento. Solo pregunta de nuevo y te mostraré opciones nuevas.",

    "notes_educate": "Estamos trabajando en la posibilidad de agregar notas a los clientes. Por ahora puedes iniciar sesión en <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a> para agregar o editar notas.",
    "mycustomers_link": "Aquí está el enlace a <a href=\"https://apps.marykayintouch.com/customer-list\" target=\"_blank\">MyCustomers</a>&nbsp; <button class=\"fdp-copy copy-link-btn\" data-copy=\"https://apps.marykayintouch.com/customer-list\">Copy Link</button>",
    "bulk_text_educate": "No puedo enviar mensajes de texto directamente a los clientes, pero si dices <strong>Do I have any followups</strong> puedes tocar el botón de texto para enviar un mensaje de seguimiento directamente desde tu teléfono.",

    # Migrated from hardcoded engine/render strings 2026-07-06 (bundle E slice).
    # Command phrases stay in English (the parsers match on them); phone-UI
    # labels use the Spanish that iOS/Android actually display.
    "app_help": (
        "<strong>Agrega MPA a tu pantalla de inicio</strong>\n\n"
        "<strong>iPhone / iPad (Safari):</strong>\n"
        "1. Toca el botón <strong>Compartir</strong> (cuadro con flecha) en la parte de abajo\n"
        "2. Desliza hacia abajo y toca <strong>Agregar a pantalla de inicio</strong>\n"
        "3. Toca <strong>Agregar</strong> — ¡listo!\n\n"
        "<strong>Android (Chrome):</strong>\n"
        "1. Toca el <strong>menú ⋮</strong> en la esquina superior derecha\n"
        "2. Toca <strong>Agregar a la pantalla principal</strong> o <strong>Instalar app</strong>\n"
        "3. Toca <strong>Agregar</strong> — ¡listo!\n\n"
        "Una vez instalada, se abre en pantalla completa sin barra del navegador, como una app de verdad."
    ),
    "inventory_help": (
        "Aquí tienes algunas cosas de inventario que puedes decir:\n"
        "\n"
        "📦 Ver y actualizar cantidades:\n"
        "• show my inventory\n"
        "• how many charcoal masks do I have\n"
        "• add 3 satin hands to inventory\n"
        "• remove 1 charcoal mask from inventory\n"
        "• set satin hands inventory to 5\n"
        "\n"
        "🎯 Fijar una cantidad deseada (tu nivel de 'siempre tener a la mano'):\n"
        "• set charcoal mask par to 3\n"
        "\n"
        "📋 Ver qué reordenar:\n"
        "• what am I low on\n"
        "• what should I order\n"
        "\n"
        "🖨️ Imprimir tu inventario:\n"
        "• print my inventory"
    ),

    # Feature-help bubbles (2026-07-06, Brian-approved copy)
    "order_help": "<strong>Pedidos por chat:</strong> solo dime la clienta y lo que quiere — como <em>\"Order for Jane Doe, charcoal mask x2 and satin lips set.\"</em><br>Yo encuentro cada producto y tú confirmas con <strong>yes</strong>, <strong>no</strong> o <strong>skip</strong>. Cuando apruebes el pedido, lo registro en MyCustomers automáticamente.<br>¿Envío directo a tu clienta? Empieza con <em>\"CDS order for…\"</em> — armo el pedido en MyCustomers y <strong>lo dejo pendiente</strong>, para que entres, agregues muestras y lo envíes a procesar cuando esté perfecto.",
    "followup_names_missing": "No encontré en tus clientas: {names}",
    "followup_help": "<strong>Seguimientos (2+2+2):</strong> llevo el control de quién compró recientemente y te recuerdo dar seguimiento — a los 2 días, 2 semanas y 2 meses de cada pedido, al estilo Mary Kay.<br>Di <strong>follow ups</strong> y te muestro tarjetas de cada clienta pendiente, con un botón de <strong>texto</strong> que abre un mensaje listo para enviar desde tu teléfono.",
    "sync_help": "<strong>Cómo funciona la sincronización:</strong> las clientas y pedidos que registras aquí llegan <strong>a</strong> MyCustomers en un par de minutos.<br>Los cambios hechos <strong>en</strong> MyCustomers (ediciones, pedidos, tus reportes de equipo) me llegan cada noche.<br>Así que si algo se ve desactualizado hoy, casi siempre se corrige para mañana en la mañana.",
    "billing_help": "<strong>Tu suscripción:</strong> $5.99 al mes, todas las funciones incluidas, cancela cuando quieras — sin contratos ni niveles.<br>Administra o cancela desde la <a href='/settings'>página de Configuración</a>.<br>¿Te encanta MPA? Di <strong>referral link</strong> — tus amigas reciben 30 días gratis, y tú un mes gratis cuando se suscriben. 💗",
    "privacy_help": "<strong>Tus datos:</strong> tus clientas, pedidos y reportes de equipo viven en nuestros servidores seguros y solo tú puedes verlos — nunca se venden, comparten, ni se usan para entrenar IA.<br>La IA lee tus mensajes del chat para entender lo que pides, pero tus registros guardados y tu contraseña de InTouch (que está cifrada) nunca salen de nuestros servidores.<br>¿Preguntas? Escribe a <a href='mailto:support@mypinkassistant.com'>support@mypinkassistant.com</a>.",

    # Unit / team query strings
    "unit_no_data": "Aún no tengo datos del equipo sincronizados. Una vez que se realice una sincronización, podré responder preguntas sobre tu equipo.",
    "unit_query_rephrase": "Tuve problemas para generar esa consulta. Por favor, intenta reformularla.",
    "unit_query_unclear": "No pude formular esa consulta. Intenta de otra forma — por ejemplo, '¿quién no tiene MyShop configurado?' o 'muestra consultoras inactivas'.",
    "unit_read_only": "Solo puedo leer datos, no modificarlos. Por favor, hazme una pregunta sobre tu equipo.",
    "unit_unsafe_query": "Esa consulta no es algo que pueda ejecutar de forma segura. Por favor, haz una pregunta de solo lectura.",
    "unit_query_error": "No pude obtener ese reporte en este momento. Intenta reformularlo, o pregunta algo como '¿quién no tiene MyShop configurado?' o '¿quién está cerca de un paquete Gran Inicio?'.",
    "data_query_rephrase": "Tuve problemas para formular una consulta para eso. Intenta reformularlo — por ejemplo, '¿quién ordenó en mayo?' o '¿cuántos pedidos el mes pasado?'.",
    "data_query_error": "No pude ejecutar esa búsqueda ahora mismo. Intenta reformular tu pregunta.",
    "data_query_no_results": "No se encontraron resultados para esa búsqueda.",
    "unit_member_not_found": "No encontré a un miembro del equipo con el nombre {name}.",
    "unit_no_results": "Ninguna consultora coincide con ese criterio.",
    "unit_consultant_count": "{n} consultora:",
    "unit_consultants_count": "{n} consultoras:",

    # unit_query.py result-formatting strings (bundle E, 2026-07-11)
    "unit_query_result_count_fallback": "{n} resultado(s) encontrado(s).",
    "unit_query_count_consultant": "{count} consultora",
    "unit_query_count_consultants": "{count} consultoras",
    "unit_query_count_result": "{count} resultado",
    "unit_query_count_results": "{count} resultados",
    "unit_query_unknown_name": "Desconocido",
    "unit_query_ends_date": "termina {month} {day}",
    "unit_query_ends_date_fallback": "termina {date}",
    "unit_query_contest_amount": "{amount} este trimestre",
    "unit_query_needed_next_bundle": "{amount} para el próximo paquete",
    "unit_query_needed_level": "{amount} para {level}",
    "unit_query_needed_next_level_generic": "{amount} para el siguiente nivel",
    "unit_query_month_achieved": "{count} mes logrado",
    "unit_query_months_achieved": "{count} meses logrados",
    "unit_query_amount_needed_qualify": "{amount} para calificar este mes",
    "unit_query_myshop_status": "MyShop: {mark}",

    # car_program.py strings (bundle E, 2026-07-11)
    "car_program_no_data": "Aún no tengo datos del programa de auto en archivo. Ejecuta primero una sincronización de reportes (esto sucede automáticamente cada noche) e inténtalo de nuevo.",
    "car_program_header": "Programa de Auto — {level} (a partir de la última sincronización)\n",
    "car_program_status": "Estado: {status_desc}",
    "car_program_current_quarter": "trimestre actual",
    "car_program_production_of_goal": "Producción de {qtr_label}: {q0} de {maint_min}",
    "car_program_remaining": "Falta: {short} este trimestre",
    "car_program_goal_met": "Meta cumplida ✓",
    "car_program_production_only": "Producción de {qtr_label}: {q0}",
    "car_program_on_target_goal": "Meta on-target: {ot_goal}  (faltan {needed_ot} más)",
    "car_program_last_quarter": "Trimestre pasado: {q1}",
    "car_program_two_quarters_ago": "Hace dos trimestres: {q2}",
    "car_program_copay_amount": "Co-pago: {copay}/mes este trimestre",
    "car_program_copay_none": "Co-pago: Ninguno ✓",
    "car_program_requal_date": "Fecha de recalificación: {date}",
    "car_program_no_award": "Ninguno",
    "car_program_status_unknown": "Desconocido",

    # render.py picker/list strings (bundle E, 2026-07-11)
    "render_customer_single_intro": "¿Es esta la persona que buscas?",
    "render_customer_multi_intro": "Encontré varias coincidencias de clientes — responde con 1-{n}:",
    "render_delete_picker_intro": "Encontré varias coincidencias. Responde con 1{suffix} para elegir qué cliente eliminar:",
    "render_delete_orders_label": "Pedidos:",
    "render_delete_no_orders": "ninguno",
    "render_delete_birthday": "Cumpleaños: {birthday}",
    "render_top5_intro_skip": "Listo — elige la mejor opción, escribe otras palabras de búsqueda, o di <strong>skip</strong> para continuar.",
    "inventory_list_intro": "Este es tu inventario actual:",
    "inventory_list_empty": "Tu inventario esta vacio.",
    "inventory_list_none_shown": "Todavía no hemos agregado ningún artículo a tu inventario.",
    "inventory_row_with_price": "• {name} {price} — {qty} disponibles",
    "inventory_row_no_price": "• {name} — {qty} disponibles",
    "inventory_item_present": "Tienes {qty} {name} en inventario.",
    "inventory_item_absent": "Tienes 0 {name} en inventario.",
    "low_stock_intro": "Esto es lo que necesitas reordenar:",
    "low_stock_none": "Estás bien surtida — nada está por debajo de tus niveles deseados.",
    "low_stock_row": "• {name} — tienes {qty}, quieres {threshold} (necesitas {needed} más)",
    "low_stock_unknown_product": "Producto desconocido",
    "propose_top_no_match": "No pude encontrar {label} en el catálogo. Intenta describirlo de otra forma (marca, línea o tono ayuda), di <strong>skip</strong> para omitir este artículo, o <strong>cancel</strong> para empezar de nuevo.",
    "propose_top_no_match_default_label": "ese producto",

    # chat_help cheat-sheet (moved verbatim from render.py's _build_chat_help_html
    # 2026-07-11; this Spanish copy already existed in render.py -- relocated only)
    "chat_help_base": '<strong>Aquí hay algunas cosas que puedes hacer en el chat:</strong>\n\n<strong>Clientes</strong>\n• Buscar un cliente — solo escribe su nombre: <em>Jane Doe</em>\n• Agregar un cliente — <em>Nuevo cliente Jane Doe, 555-1234, jane@gmail.com</em>\n• Qué ordenó alguien — <em>¿Qué ordenó Jane?</em>\n\n<strong>Pedidos</strong>\n• Hacer un pedido — <em>Pedido para Jane: 2 labiales y una base</em>\n• Buscar un producto y precio — <em>Satin hands</em> o <em>¿Cuánto cuesta la mascarilla de carbón?</em>\n\n<strong>Tus clientes</strong>\n• Por ciudad — <em>Clientes en Houston</em>\n• Sin pedidos recientes — <em>¿Quién no ha ordenado en 3 meses?</em>\n• Mejores compradoras — <em>¿Cuáles son mis mejores clientes?</em>\n• Cumpleaños — <em>¿Quién cumple años este mes?</em>\n\n<strong>Inventario</strong>\n• Verificar existencias — <em>¿Cuántas mascarillas de carbón tengo?</em>\n• Establecer mínimo — <em>Set charcoal mask par to 3</em>\n\n<strong>Otro</strong>\n• Look Book actual — <em>Look book</em>\n• Orden de aplicación — <em>Orden de aplicación</em>\n• Tablas de conversión de tonos — <em>Tabla de conversión</em>\n• Tu enlace de referido — <em>Mi enlace de referido</em>',
    "chat_help_team_extra": '\n\n<strong>Tu equipo</strong>\n• <em>¿Quiénes son mis consultoras?</em>\n• <em>¿Quién no ha configurado MyShop?</em>\n• <em>¿Quién está cerca de un paquete Gran Inicio?</em>\n• <em>¿Quién es el equipo de Sarah?</em>',

    # catalog.py product-lookup strings (bundle E, 2026-07-11)
    "product_lookup_header": "Búsqueda de producto",
    "product_fact_sheet_link": "Ficha del producto",
    "product_order_of_application_link": "Orden de aplicación",
    "order_of_application_reply": 'Aquí está la <a href="{url}" target="_blank">tabla de Orden de aplicación</a>&nbsp; <button class="fdp-copy copy-link-btn" data-copy="{url}">Copiar enlace</button>',

    # Tablas de conversión de tonos (2026-07-27). MK publica edición en español
    # del corrector, el polvo y el delineador; base y "Range and Category" solo
    # existen en inglés, así que esas dos enlazan al PDF en inglés.
    "conversion_chart_header": "<strong>Tablas de conversión de tonos</strong>",
    "conversion_chart_row": '• <a href="{url}" target="_blank">{label}</a>',
    "conversion_chart_single": 'Aquí está la <a href="{url}" target="_blank">{label}</a>',
    "conversion_chart_more": "\n\nDi <em>tablas de conversión</em> para verlas todas.",
    "conversion_chart_label_foundation": "TimeWise 3D Foundation — Conversión de tonos nuevos (inglés)",
    "conversion_chart_label_concealer": "Concealer — Conversión de tonos",
    "conversion_chart_label_powder": "Información del Silky Setting Powder",
    "conversion_chart_label_lip_liner": "Tabla de conversión del Waterproof Lip Liner",
    "conversion_chart_label_range": "TimeWise 3D Foundations — Range and Category Chart (inglés)",
    "product_conversion_chart_link": "Tabla de conversión de tonos",
    "sales_tax_set": "✅ Tasa de impuesto de ventas establecida en <strong>{rate}%</strong>. La agregaré a tus pedidos de My Inventory de ahora en adelante — di <strong>sin impuesto</strong> en un pedido para omitirla, o establécela en 0 para desactivarla.",
    "sales_tax_cleared": "✅ Impuesto de ventas desactivado. Tus pedidos no incluirán impuesto.",
    "sales_tax_show": "Tu tasa de impuesto de ventas es <strong>{rate}%</strong>. Di <em>establecer mi impuesto de ventas en 7.5%</em> para cambiarla, o establécela en 0 para desactivarla.",
    "sales_tax_unset": "No tienes una tasa de impuesto de ventas configurada, así que los pedidos no incluyen impuesto. Di <em>establecer mi impuesto de ventas en 7.5%</em> y la agregaré automáticamente a tus pedidos de My Inventory.",
    "sales_tax_invalid": "No pude leer esa tasa. Intenta <em>establecer mi impuesto de ventas en 7.5%</em> (0–100).",
    "customer_tax_save_prompt": "💡 ¿Quieres que guarde <strong>{rate}%</strong> como la tasa de impuesto de {name} para futuros pedidos? Responde <strong>sí</strong> para guardarla.",
    "customer_tax_save_prompt_exempt": "💡 ¿Quieres que guarde a {name} como <strong>exento de impuestos</strong> para que sus futuros pedidos no incluyan impuesto? Responde <strong>sí</strong> para guardarlo.",
    "customer_tax_saved": "✅ ¡Guardado! Los pedidos de {name} usarán <strong>{rate}%</strong> de impuesto de ventas de ahora en adelante.",
    "customer_tax_saved_exempt": "✅ ¡Guardado! {name} quedó como exento de impuestos — sus pedidos no incluirán impuesto de ventas.",
    "customer_tax_set": "✅ Tasa de impuesto de {name} establecida en <strong>{rate}%</strong>. Sus pedidos la usarán automáticamente.",
    "customer_tax_cleared": "✅ Se borró la tasa de impuesto guardada de {name}. Sus pedidos vuelven a tu tasa predeterminada.",
    "customer_tax_show": "La tasa de impuesto guardada de {name} es <strong>{rate}%</strong>. Di <em>establecer el impuesto de {name} en 5.5%</em> para cambiarla, o <em>borrar el impuesto de {name}</em> para quitarla.",
    "customer_tax_show_exempt": "{name} está guardado como <strong>exento de impuestos</strong> — sus pedidos no incluyen impuesto de ventas. Di <em>borrar el impuesto de {name}</em> para deshacerlo.",
    "customer_tax_unset": "{name} no tiene una tasa de impuesto guardada — sus pedidos usan tu tasa predeterminada. Di <em>establecer el impuesto de {name} en 5.5%</em> para guardar una.",
    "customer_tax_save_declined": "👍 De acuerdo — no la guardaré.",
    "customer_tax_ambiguous": "Encontré más de un cliente que coincide con {name} — intenta de nuevo con el nombre completo, como <em>establecer el impuesto de Jane Smith en 5.5%</em>.",
    "inventory_category_header": "<strong>{label} en inventario</strong> — {total} disponibles:",
    "inventory_category_empty": "No tienes productos de {label} en tu inventario en este momento.",
    "product_history_header": "<strong>{filter} de {name}:</strong>",
    "product_history_none": "No veo {filter} en el historial de pedidos de {name}.",
    "product_part_number": "Parte # {sku}",
    "product_lookup_not_found_bullet": "• No pude encontrar \"{name}\"",
        "render_top5_intro": "Listo \u2014 elige la mejor opción (responde {range}), o escribe otras palabras de búsqueda:",

    # inventory_guardrail (bundle E, 2026-07-11)
    "inventory_guardrail": (
        "Eso parece una actualización de inventario.\n"
        "Inténtalo de nuevo usando la palabra 'inventory':\n"
        "• add 3 satin hands to inventory\n"
        "• remove 1 satin hands from inventory\n"
        "• set satin hands inventory to 5"
    ),

    # Cadenas migradas del engine.py 2026-08-17 (paridad de español).
    # cancel/skip tienen formas en español reconocidas ("cancelar", "omitir");
    # DELETE, los comandos de ejemplo ("invoice Jane Smith", "customers in
    # Madison", "keep 3 ... on hand") y el botón "Send invoice" quedan en
    # inglés — los parsers y botones solo reconocen esas formas.

    # búsqueda de productos / categorías
    "category_big_list_hint": "Es mucho para mostrar — aquí está por tipo (toca uno):",
    "category_product_count": "{n} productos",
    "more_products_link": "+{n} más",
    "product_search_no_matches": "No encontré productos que coincidan con esa búsqueda.",
    "product_not_found_try_different": "No encontré ese producto en el catálogo. Intenta con otro nombre o con parte del nombre.",
    "product_one_at_a_time": "Puedo buscar un solo producto a la vez — intenta buscar cada uno por separado.",
    "look_book_line": 'Aquí está <a href="{url}" class="inapp-overlay-link">{label}</a>&nbsp; <button class="fdp-copy copy-link-btn" data-copy="{url}">Copiar enlace</button>',
    "inventory_no_thresholds": "Aún no has fijado niveles deseados de inventario.\nPrueba: \"keep 3 charcoal mask on hand\" y yo lo llevaré por ti.",

    # confirmaciones de eliminar clienta (DELETE queda en inglés a propósito)
    "delete_customer_confirm_orders": "Esto eliminará a {name} de MyPinkAssistant y también quitará {count} pedido(s) local(es). Escribe DELETE para confirmar, o `cancelar`.",
    "delete_customer_confirm_plain": "Esto eliminará a {name} de MyPinkAssistant. Escribe DELETE para confirmar, o <strong>cancelar</strong>.",

    # redirección de ediciones de clienta
    "edit_request_redirect": 'Los cambios o actualizaciones a la información de una clienta por ahora se hacen desde <a href="https://apps.marykayintouch.com/customer-list" target="_blank">MyCustomers</a>. Los cambios aparecerán en MyPinkAssistant en la próxima sincronización.',

    # selector clienta-vs-consultora
    "picker_found_options": "Encontré estas opciones — ¿cuál querías decir?",
    "picker_multiple_matches": "Encontré varias coincidencias — responde con 1 o {total}:",
    "picker_label_customer": "Clienta",
    "picker_label_consultant": "Consultora",

    # facturas. invoice_sent debe quedar en TEXTO PLANO (sin HTML) — ver la
    # nota en el dict de inglés.
    "invoice_how": "Para enviar una factura, abre los pedidos de la clienta y toca <strong>Send invoice</strong> en el pedido que quieras.",
    "invoice_no_email_sync": "No tengo correo electrónico de {name}, así que no hay a dónde enviar la factura. Agrega su correo en MyCustomers y se sincronizará.",
    "invoice_who": "¿Para quién es la factura? Escribe algo como <strong>invoice Jane Smith</strong> y te mostraré sus pedidos.",
    "invoice_no_orders": "No veo pedidos de {name} para facturar.",
    "invoice_which_order": "¿Cuál pedido?",
    "invoice_order_not_found": "No encontré ese pedido.",
    "invoice_no_email_short": "No tengo correo electrónico de {name}.",
    "invoice_cds_blocked": "Ese pedido lo envió Mary Kay directamente, así que ya le cobraron a tu clienta — no hay factura que enviar.",
    "invoice_unpriced_blocked": "No puedo enviar ese — no tengo precio registrado de todo lo que incluye, y tu clienta vería un artículo como gratis. La sincronización nocturna normalmente completa esos precios.",
    "invoice_send_failed": "No pude enviar la factura en este momento. Espera un minuto e intenta de nuevo — si sigue fallando, escribe a support@mypinkassistant.com.",
    "invoice_sent": "✅ Factura enviada a {name} ({email}).",

    # lista PCP
    "pcp_none": "No encontré clientas PCP para el trimestre actual.",
    "pcp_header": "<strong>Lista PCP</strong> ({remaining} pendientes · {total} en total)",

    # más vendidos + etiquetas de período compartidas
    "top_sellers_none": "No encontré historial de pedidos para {label}.",
    "top_sellers_header": "<strong>Tus más vendidos</strong> ({label})",
    "top_sellers_row": "{i}. {name} — {qty} unidades",
    "period_this_month": "este mes",
    "period_this_quarter": "este trimestre",
    "period_this_year": "este año",
    "period_all_time": "todo el tiempo",
    "period_last_12_months": "los últimos 12 meses",
    "period_today": "hoy",
    "period_tomorrow": "mañana",
    "period_this_week": "esta semana",
    "period_next_week": "la próxima semana",
    "period_next_month": "el próximo mes",
    "period_next_30_days": "los próximos 30 días",

    # cumpleaños — {scope} va después de "Cumpleaños" (ver nota en inglés)
    "bday_in_month": "en {month}",
    "month_names": "enero,febrero,marzo,abril,mayo,junio,julio,agosto,septiembre,octubre,noviembre,diciembre",
    "bday_none": "No hay {who} con cumpleaños {period}.",
    "bday_who_customers": "clientas",
    "bday_who_consultants": "consultoras",
    "bday_who_both": "clientas o consultoras",
    "bday_header": "<strong>Cumpleaños{scope} {period}</strong>",
    "bday_scope_customers": " de clientas",
    "bday_scope_consultants": " de consultoras",
    "bday_scope_both": "",

    # clientas inactivas (expansión "show all")
    "lapsed_no_more": "No hay más clientas inactivas después de las primeras 5.",
    "lapsed_all_header": "Todas las clientas inactivas ({period}+):",
    "unit_month": "mes",
    "unit_months": "meses",
    "unit_days": "días",
    "months_ago": "hace {n} meses",
    "days_ago": "hace {n} días",

    # búsqueda por ciudad (los comandos de ejemplo quedan en inglés)
    "city_lookup_hint": "Esto parece una búsqueda por ciudad/estado. Prueba \"customers in Madison\" o \"customers in Madison, WI\"",

    # validaciones al confirmar una clienta nueva
    "cust_need_full_name": "Necesito nombre y apellido para que MyCustomers pueda guardar a esta clienta. Escribe <strong>cancelar</strong> y vuelve a ingresarla con el nombre completo.",
    "cust_bad_phone": "El número de teléfono que tengo ({phone}) no tiene 10 dígitos — MyCustomers requiere un número de EE. UU. de 10 dígitos. Escribe el número correcto o di cancelar.",
    "cust_partial_address": "Solo veo una dirección incompleta. Escribe la dirección completa (calle, ciudad, estado y código postal) — o escribe “sin dirección” para guardar sin dirección.",
    "cust_bad_state": "No pude reconocer \"{state}\" como un estado válido. Vuelve a escribir la dirección con el nombre completo del estado (p. ej. Texas) o su abreviatura (p. ej. TX), o di cancelar.",
    "cust_bad_zip": "El código postal que tengo ({zip}) no parece válido — MyCustomers requiere un código postal de 5 dígitos (o ZIP+4 como 12345-6789). Escribe el código postal correcto o di cancelar.",
    "cust_email_space": "El correo que tengo ({email}) tiene un espacio — escríbelo de nuevo sin el espacio, o di cancelar.",
    "cust_email_invalid": "El correo que tengo ({email}) no parece válido — escribe el correo correcto o di cancelar.",
    "cust_future_birthday": "El cumpleaños que tengo ({birthday}) está en el futuro — escribe el cumpleaños correcto o di cancelar.",

    # guardia de awaiting_order_items
    "add_item_prompt": "No veo un artículo que pueda agregar al pedido de {first} {last}. Escribe lo que quieras agregar al pedido o di cancelar para empezar de nuevo.",

    # notas de confirmación de customer_edits.py
    "edit_notes_prefix": "Actualizado: ",
    "edit_note_email": "Correo actualizado",
    "edit_note_phone": "Teléfono actualizado",
    "edit_note_birthday": "Cumpleaños actualizado",
    "edit_note_referred_by": "Referida por actualizado",
    "edit_note_tags": "Etiquetas actualizadas",
    "edit_note_address": "Dirección actualizada",
    "edit_note_address_street": "Dirección actualizada (calle)",
    "edit_note_zip": "Código postal actualizado",
    "edit_note_address_removed": "Dirección eliminada — se guardará sin dirección",
    "edit_note_failed": "No pude aplicar: “{raw}”",
}
