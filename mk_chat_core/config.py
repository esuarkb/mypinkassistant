"""Package-wide constants."""
from pathlib import Path

# -------------------------
# Paths / Settings
# -------------------------
# This file lives inside the mk_chat_core/ package — project root is one
# level up (catalog/, data/ are at the project root, not in the package)
BASE_DIR = Path(__file__).resolve().parent.parent
CATALOG_DIR = BASE_DIR / "catalog"
MODEL = "gpt-4.1-mini"

MATCH_LIMIT = 25
TOP5 = 5
