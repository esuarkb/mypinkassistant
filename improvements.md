# Chat Engine Improvements — Prioritized Work List

This document was prepared after a full codebase review. Work through these
in priority order. Do not tackle more than one at a time without testing.
Do not touch playwright_automation/ scripts during any of this work.

## Priority 1 — Fix Before or Right After Launch

### 1. Graceful OpenAI Timeout Handling
**File:** `app.py` (chat endpoint), `mk_chat_core.py`
**Problem:** If OpenAI API is slow or has a hiccup, the chat endpoint hangs
until it times out and returns a raw error message to the user.
**Fix:** Wrap OpenAI calls in a timeout (suggest 30 seconds) with a
friendly fallback message if it fails.
**Target response to user:** "I'm having a little trouble right now,
please try again in a moment." Never expose the raw exception.
**Impact:** Directly affects beta tester experience right now.

### 2. Intent Routing — Fold Into Main Prompt
**File:** `intent_router.py`, `mk_chat_core.py`
**Problem:** Every chat message currently makes at least two OpenAI API
calls — one for intent classification in intent_router.py and one for
the main response. This adds latency to every single message.
**Fix:** Fold intent detection into the main prompt as a structured
output (JSON mode or function calling). One API call per message instead
of two.
**Impact:** Cuts response time roughly in half for simple queries like
customer lookups. Reduces OpenAI costs. Users will notice the speed
improvement immediately.
**Caution:** Test thoroughly — intent routing is central to everything
the chat engine does. Verify all intents still work correctly after:
- Customer lookup (name, phone, email, birthday, address)
- Order entry and confirmation
- Inventory queries
- Customer creation
- Order history lookup

---

## Priority 2 — Soon After Launch

### 3. Database Connection Pooling
**File:** `db.py`, `app.py`
**Problem:** The chat endpoint opens a fresh database connection for
every single message. For quick lookups this is unnecessary overhead
that adds latency, especially under concurrent load.
**Fix:** Implement connection pooling.
- For PostgreSQL (production): use psycopg_pool
- For SQLite (local dev): existing behavior is acceptable, pool not
  needed locally
- Only pool the Postgres connection in production
**Impact:** Faster responses under load, more efficient resource use
as consultant count grows. Important for scaling to hundreds of users.
**Note:** Keep SQLite local dev behavior unchanged — do not break the
dual-DB setup.

### 4. Long Session Context Summarization
**File:** `mk_chat_core.py` (session state management)
**Problem:** Session state stores raw conversation history. In long
sessions the context window fills up with old exchanges, which:
- Slows OpenAI response times
- Increases API costs
- Can cause context window overflow errors
**Fix:** When conversation history exceeds ~10 exchanges, summarize
older messages into a brief paragraph and keep only recent exchanges
in full. Store the summary in session state alongside recent history.
**Example summary format:**
"Earlier in this session the consultant looked up Jane Smith's contact
info and placed an order for 2 lipsticks. They also added a new
customer named Maria Garcia."
**Impact:** Keeps response times consistent in long sessions. Controls
OpenAI costs as usage grows.

---

## Priority 3 — Architectural (Schedule a Focused Session)

### 5. Catalog Search Optimization
**File:** `mk_chat_core.py`
**Problem:** Product catalog matching happens fresh for each item in
an order. The catalog is static (loaded from CSV at startup) but the
search index is rebuilt repeatedly during order processing.
**Fix:** At startup, build a preprocessed search index from the catalog
and keep it in memory. Reuse this index for all catalog lookups.
**Impact:** Multi-item orders process significantly faster. Reduces
redundant computation on every order.
**Note:** Catalog is already partially loaded at startup — this
extends that pattern to the search index as well.

### 6. Split mk_chat_core.py Into Modules
**File:** `mk_chat_core.py` (currently ~2500 lines)
**Problem:** One file handles intent parsing, CRM operations, order
building, catalog matching, and session management. This causes:
- Hard to isolate bugs
- Risky to update one feature without affecting others
- Slow to navigate and reason about
- Every AI session has to load and understand the entire file
**Suggested module split:**
- `chat_engine.py` — main handle_message loop and session management
- `order_builder.py` — order drafting, item resolution, confirmation flow
- `crm_ops.py` — customer lookup, create, delete operations via chat
- `catalog_search.py` — product matching and catalog utilities
- `chat_prompts.py` — all prompt templates in one place
**Approach:** Do this incrementally, one module at a time, with full
testing after each extraction. Do NOT do this all at once.
**Impact:** Long term maintainability, easier to add premium features,
faster to debug issues.

---

## General Rules For All of This Work
- Test locally after every change before committing
- Do not touch playwright_automation/ scripts during any of this work
- Keep SQLite/Postgres dual-DB compatibility intact for all changes
- Never return raw exception messages to the user
- Run the app and verify chat works end to end after each improvement
- Commit each improvement separately with a clear commit message
- If anything looks risky or unclear, stop and ask before proceeding

---

## Internationalization (i18n) — Build Ready For Spanish & Future Languages

### Current State
- Language toggle exists in settings (en/es)
- Catalog loads from en.csv or es.csv based on language setting
- Chat prompts, AI responses, error messages, and UI strings are
  English-only throughout mk_chat_core.py and app.py
- Spanish mode is not fully functional yet — do not advertise it

### Goal
Full Spanish chat experience where:
- AI responds in Spanish when consultant language = 'es'
- All confirmation messages, error messages, and prompts are in Spanish
- Catalog matching works against es.csv
- Easily extensible to additional languages later (Portuguese, French)

### The Right Way To Build This

#### Step 1 — Externalize all strings (do this incrementally as files are touched)
Instead of hardcoded English strings scattered through the code, move
all user-facing strings to a central location:

**Create `strings.py`:**
'''python
STRINGS = {
    "en": {
        "order_confirm": "Got it! Here's your order summary:",
        "customer_not_found": "I couldn't find a customer with that name.",
        "login_required": "Please log in to continue.",
        "billing_inactive": "Your subscription is inactive. Please subscribe to continue.",
        "error_generic": "I'm having a little trouble right now, please try again in a moment.",
        # ... all user-facing strings
    },
    "es": {
        "order_confirm": "¡Entendido! Aquí está el resumen de tu pedido:",
        "customer_not_found": "No encontré un cliente con ese nombre.",
        "login_required": "Por favor inicia sesión para continuar.",
        "billing_inactive": "Tu suscripción está inactiva. Por favor suscríbete para continuar.",
        "error_generic": "Estoy teniendo un pequeño problema, por favor intenta de nuevo en un momento.",
        # ... all user-facing strings
    }
}

def get_string(key: str, lang: str = "en") -> str:
    language = lang if lang in STRINGS else "en"
    return STRINGS[language].get(key, STRINGS["en"].get(key, key))
'''

#### Step 2 — Pass language into the chat engine
The consultant's language preference is already stored in the DB.
Make sure it's passed into handle_message() and available throughout
the chat flow so prompts and responses can be language-aware.

**In mk_chat_core.py handle_message():**
'''python
# Already have consultant dict — make sure language flows through
lang = (consultant.get("language") or "en").strip().lower()
# Pass lang to all response builders and prompt templates
'''

#### Step 3 — Language-aware AI prompts
The system prompt sent to OpenAI should instruct the AI to respond
in the consultant's language:

'''python
def build_system_prompt(lang: str = "en") -> str:
    language_instruction = (
        "Always respond in Spanish." if lang == "es"
        else "Always respond in English."
    )
    return f"""You are MyPinkAssistant, a helpful CRM assistant for
Mary Kay consultants. {language_instruction}
... rest of prompt ...
"""
'''

#### Step 4 — UI strings
The HTML pages use {{PLACEHOLDER}} template substitution already.
Extend this pattern to support language-specific UI strings rather
than hardcoding English in the HTML files.

### Rules For This Work
- Do NOT attempt full Spanish implementation in one session
- Externalize strings gradually as you touch each file for other reasons
- Have a fluent Spanish speaker review all Spanish strings before launch
- Test Spanish mode end to end before advertising it to consultants
- Keep 'en' as the default fallback for any missing translations

### Timeline Suggestion
- **Before launch:** Hide or label Spanish as "coming soon" if not fully working
- **30-60 days post launch:** Implement strings.py and language-aware prompts
- **When ready:** Beta test Spanish mode with a small group of Spanish-speaking
  consultants before general release
- **Future:** Same pattern extends cleanly to Portuguese, French, etc.