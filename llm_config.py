# llm_config.py
"""THE one place the OpenAI model is chosen.

Every OpenAI call in the app (intent classification fallback, order/customer
parsing, product candidate picking, unit_query and data_query text-to-SQL)
gets its model from here via model_kwargs().

TO CHANGE THE MODEL:
  1. Edit OPENAI_MODEL below — or set the MK_OPENAI_MODEL env var (lets you
     try a model on Render without a code change, or A/B locally).
  2. Run the full golden suite:  python test_intent_golden.py
  3. Ideally also A/B the intent fallback + order parser over recent
     intent_logs messages before trusting it (see memory/CLAUDE.md notes
     from the 2026-07 gpt-4.1-mini -> gpt-5-mini migration).

Model history:
  gpt-4.1-mini  launch .. 2026-07  (OpenAI API retirement 2026-10-14)
  gpt-5-mini    2026-07 ..
"""
import os

OPENAI_MODEL = os.getenv("MK_OPENAI_MODEL", "gpt-5-mini")


def model_kwargs(effort: str = "minimal") -> dict:
    """Kwargs for client.responses.create — model plus any family-specific
    settings. GPT-5-family models are reasoning models: default reasoning
    effort is minimal so chat stays fast and we don't pay for thinking tokens.
    Tasks that benefit from a beat of thinking pass effort="low" (the
    text-to-SQL generators do — evaluated 2026-07-03: minimal-effort SQL
    picked wrong columns on ~1 in 3 runs; low was stable)."""
    kw = {"model": OPENAI_MODEL}
    if OPENAI_MODEL.startswith(("gpt-5", "o")):
        kw["reasoning"] = {"effort": effort}
    return kw
