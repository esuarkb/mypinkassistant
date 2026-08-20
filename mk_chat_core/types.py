"""Shared types for the mk_chat_core package."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatReply:
    reply: str
    # The intent_logs row this reply answers, so app.py can pair response_text
    # to the EXACT row. None when no row was logged for this reply (the
    # show_all_products early returns) — app.py must then skip the update
    # entirely, not fall back to "latest row for the consultant": that fallback
    # overwrote the PREVIOUS message's response and fabricated intent/response
    # contradictions in the logs (weed-garden 2026-08-20 F3).
    intent_log_id: Optional[int] = None
