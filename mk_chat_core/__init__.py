"""
mk_chat_core — the chat engine package (split from the single 6,100-line
mk_chat_core.py on 2026-07-02; step 3 of the chat-core reorganization).

External code keeps importing exactly what it always did:

    from mk_chat_core import MKChatEngine, insert_job, normalize_state, ...

Package map (what lives where):
    engine.py         MKChatEngine.handle_message — dispatch + handlers + pending flows
    types.py          ChatReply
    config.py         BASE_DIR, CATALOG_DIR, MODEL, MATCH_LIMIT, TOP5
    dbutil.py         PH placeholder, db_connect
    session.py        per-consultant chat session state (pending flow, last customer)
    jobs.py           insert_job + first-sync queueing after billing activation
    catalog.py        catalog loading, exact/fuzzy product matching, product formatting
    order_parse.py    OpenAI order/customer parser + deterministic order-text helpers
    normalize.py      phone/state/city/birthday/address normalizers
    customer_edits.py parsing corrections to a pending customer confirm
    render.py         HTML for pickers, proposals, inventory lists, help pages
    ui_text.py        every user-facing string, EN + ES (keep both dicts in sync!)
    unit_query.py     director team questions (text-to-SQL)
    data_query.py     cross-customer/aggregate questions (text-to-SQL)
    car_program.py    career car status + co-pay schedule

Routing does NOT live here — see intent_router.py (route() + its docstring).
"""

from .catalog import get_catalog_path_for_language, load_catalog
from .engine import MKChatEngine
from .jobs import insert_job, maybe_queue_initial_customer_import
from .normalize import (
    birthday_display,
    format_phone_display,
    normalize_birthday,
    normalize_city,
    normalize_phone,
    normalize_state,
    parse_address_line,
)
from .session import ensure_sessions_table, load_session_state, save_session_state
from .types import ChatReply
