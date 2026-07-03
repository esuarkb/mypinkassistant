"""Package-wide constants."""
from pathlib import Path

# -------------------------
# Paths / Settings
# -------------------------
# This file lives inside the mk_chat_core/ package — project root is one
# level up (catalog/, data/ are at the project root, not in the package)
BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_DIR = BASE_DIR / "catalog"
# Model choice lives in llm_config.py at the project root — ONE place for the
# whole app. MODEL kept as an alias for existing imports; call sites pass
# **model_kwargs() so family-specific settings (reasoning effort) apply too.
from llm_config import OPENAI_MODEL as MODEL, model_kwargs  # noqa: F401

MATCH_LIMIT = 25
TOP5 = 5
