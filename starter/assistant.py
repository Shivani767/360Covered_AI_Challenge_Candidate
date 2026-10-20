"""Backwards-compatible entry point.

The original starter module lived here and the reviewer harness imports
``CoverageAssistant`` from ``starter.assistant``. The implementation has
moved to the ``coverage_assistant`` package; this file keeps the original
import path working so the supplied UI and the supplied smoke test still
run unchanged.

What changed versus the original starter (see ``docs/ROOT_CAUSE.md`` for the
full table):

* the allowed plan set is ``eligible_ids`` AND ``visible_ids`` (the starter
  ignored ``visible_ids`` entirely and fell back to the whole catalog),
* an unknown or empty plan set no longer raises ``IndexError`` or silently
  resolves to a made-up "best plan",
* the offline answer is a deterministic, catalog-grounded response that is
  explicitly labelled as **not** an LLM, instead of "It covers everything
  you asked about",
* the LLM is called with a fact pack built in code, and the output is
  re-validated against the catalog before it is returned.

Usage::

    from starter.assistant import CoverageAssistant
    bot = CoverageAssistant()              # deterministic offline mode
    bot = CoverageAssistant(mode="live")   # real LLM, needs an API key
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coverage_assistant import CoverageAssistant  # noqa: E402,F401
from coverage_assistant.catalog import Catalog  # noqa: E402,F401

__all__ = ["CoverageAssistant", "Catalog", "PLANS", "ROOT"]

# Kept for backwards compatibility with anything that imported PLANS.
PLANS = dict(Catalog.load().plans)


if __name__ == "__main__":
    state = {
        "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
        "visible_ids": ["P-BASE", "P-PLUS"],
        "selected_id": "P-PLUS",
        "selected_options": [],
    }
    bot = CoverageAssistant()
    print(bot.mode_label)
    print(bot.answer("Which plan has the most coverage?", state))
