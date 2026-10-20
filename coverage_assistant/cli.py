"""Command line entry point.

Offline (no credentials, not an LLM)::

    python -m coverage_assistant.cli --question "What is my deductible?"

Live LLM (requires an API key in the environment)::

    export OPENAI_API_KEY=sk-...
    python -m coverage_assistant.cli --mode live --question "What is my deductible?"

Other providers::

    export ANTHROPIC_API_KEY=...      # --mode live picks Anthropic automatically
    export LLM_BASE_URL=http://127.0.0.1:11434/v1   # any OpenAI-compatible server
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from .assistant import CoverageAssistant
from .catalog import Catalog

DEFAULT_STATE: Dict[str, Any] = {
    "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
    "visible_ids": ["P-BASE", "P-PLUS"],
    "selected_id": "P-PLUS",
    "selected_options": [],
}


def parse_state(raw: str) -> Dict[str, Any]:
    """Accept a state as JSON, or build a default state from simple flags."""
    if not raw:
        return dict(DEFAULT_STATE)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--state is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise SystemExit("--state must be a JSON object.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coverage_assistant",
        description="Ask a coverage question about the synthetic 360Covered catalog.",
    )
    parser.add_argument(
        "--question", "-q", default="", help="The customer question."
    )
    parser.add_argument(
        "--mode",
        choices=["offline", "live"],
        default=None,
        help=(
            "offline = deterministic adapter (NOT an LLM); live = real LLM call. "
            "Defaults to the ASSISTANT_MODE environment variable, then 'offline'."
        ),
    )
    parser.add_argument(
        "--state",
        default="",
        help='State as JSON, e.g. \'{"eligible_ids":["P-BASE"],"visible_ids":["P-BASE"]}\'',
    )
    parser.add_argument(
        "--show-trace",
        action="store_true",
        help="Print the internal trace (intent, referent, allowed ids, violations).",
    )
    parser.add_argument(
        "--list-plans",
        action="store_true",
        help="List the catalog plans and exit.",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_plans:
        catalog = Catalog.load()
        for plan_id in catalog.plan_ids():
            facts = catalog.plan_facts(plan_id)
            print(
                f"{plan_id}  {facts['name']}  {facts['monthly_price_display']}/month  "
                f"deductible {facts['deductible_display']}"
            )
        return 0

    if not args.question:
        build_parser().print_usage()
        print("error: --question is required (or use --list-plans)", file=sys.stderr)
        return 2

    state = parse_state(args.state)

    mode = args.mode or os.environ.get("ASSISTANT_MODE") or "offline"

    try:
        assistant = CoverageAssistant(mode=mode)
    except Exception as exc:
        # Live mode without credentials must fail loudly rather than
        # silently degrade to the offline adapter, which would look like a
        # successful run.
        print(f"Could not start the assistant: {exc}", file=sys.stderr)
        print(
            "Run without --mode live (or set ASSISTANT_MODE=offline) for the "
            "deterministic, credential-free mode.",
            file=sys.stderr,
        )
        return 2

    print(f"[mode] {assistant.mode_label}")
    answer = assistant.answer(args.question, state)
    print()
    print(answer)

    if args.show_trace and assistant.last_trace is not None:
        print()
        print("[trace] " + json.dumps(assistant.last_trace.as_dict(), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
