"""Shared helpers for the evaluation suite (kept importable without pytest)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCENARIOS_PATH = ROOT / "data" / "scenarios.json"
OFFLINE_LABEL = "OFFLINE_DETERMINISTIC"


def load_scenarios():
    with open(SCENARIOS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def strip_label(answer: str) -> str:
    """Remove the offline banner so assertions look at the content only."""
    if OFFLINE_LABEL in answer:
        parts = answer.split("\n\n", 1)
        return parts[1] if len(parts) > 1 else answer
    return answer
