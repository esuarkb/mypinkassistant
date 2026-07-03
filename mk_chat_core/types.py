"""Shared types for the mk_chat_core package."""
from dataclasses import dataclass


@dataclass
class ChatReply:
    reply: str
