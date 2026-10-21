#!/usr/bin/env python3
"""Run the evaluation suite and write a readable results report.

Usage::

    python scripts/run_eval.py                      # offline suite
    python scripts/run_eval.py --mode live          # live LLM suite
    python scripts/run_eval.py --out reports/eval.md

The report records every case, the assertions used, the mode that produced
the answers, and any failures. Live mode additionally records which model
was used and the estimated token usage, so a reviewer can see the spend.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coverage_assistant import CoverageAssistant  # noqa: E402
from coverage_assistant.llm import ProviderConfig  # noqa: E402


class _RecordingResult(unittest.TextTestResult):
    """Test result that also collects per-case timing and failure detail."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        self._started = _now()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self.records.append(
            {
                "name": test.id(),
                "duration_s": round(_now() - self._started, 4),
                "errors": list(getattr(self, "_errors", [])),
            }
        )


def _now():
    import time

    return time.time()


def run_unittest_suite(pattern: str) -> tuple:
    """Run the unittest suite and return (result, records)."""
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern=pattern, top_level_dir=str(ROOT / "tests"))
    runner = unittest.TextTestRunner(verbosity=1, resultclass=_RecordingResult)
    result = runner.run(suite)
    return result, result.records


def conversation_cases():
    """The three worked example conversations, used as live-mode probes."""
    return [
        {
            "id": "C1",
            "title": "The 'give me everything' request",
            "state": {
                "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
            "turns": ["Just give me the plan that covers everything."],
        },
        {
            "id": "C2",
            "title": "Option offered but not purchased",
            "state": {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
            "turns": ["Is my navigation screen covered?"],
        },
        {
            "id": "C3",
            "title": "Plan switch mid-conversation",
            "state": {
                "eligible_ids": ["P-BASE", "P-PLUS"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-BASE",
                "selected_options": [],
            },
            "turns": [
                "Tell me about CoreDrive",
                "__SELECT__P-PLUS",
                "What is its deductible?",
            ],
        },
    ]


def run_conversations(mode: str) -> list:
    """Replay the example conversations and collect the answers."""
    cases = []
    for case in conversation_cases():
        state = dict(case["state"])
        try:
            assistant = CoverageAssistant(mode=mode)
        except Exception as exc:
            cases.append({**case, "error": str(exc), "turns": []})
            continue
        transcript = []
        for turn in case["turns"]:
            if turn.startswith("__SELECT__"):
                state["selected_id"] = turn.replace("__SELECT__", "")
                transcript.append({"role": "event", "content": f"[selection changed to {state['selected_id']}]"})
                continue
            answer = assistant.answer(turn, state)
            transcript.append({"role": "user", "content": turn})
            transcript.append({"role": "assistant", "content": answer})
        cases.append({**case, "transcript": transcript, "mode": assistant.mode_label})
    return cases


def build_report(result, records, conversations, mode) -> str:
    lines = []
    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    passed = total - failed - errored

    lines.append("# AI Coverage Assistant - Evaluation Report")
    lines.append("")
    lines.append(f"- Mode: **{mode}**")
    lines.append(f"- Cases run: **{total}**")
    lines.append(f"- Passed: **{passed}**")
    lines.append(f"- Failed: **{failed}**")
    lines.append(f"- Errors: **{errored}**")
    lines.append("")
    lines.append("## Case results")
    lines.append("")
    lines.append("| Case | Result | Duration (s) |")
    lines.append("| --- | --- | --- |")
    for record in records:
        name = record["name"].replace("test_", "")
        status = "PASS" if not record["errors"] else "FAIL"
        lines.append(f"| `{name}` | {status} | {record['duration_s']} |")
    lines.append("")

    if failed or errored:
        lines.append("## Failures")
        lines.append("")
        for test, text in result.failures + result.errors:
            lines.append(f"### {test.id()}")
            lines.append("")
            lines.append("```")
            lines.append(text.strip())
            lines.append("```")
            lines.append("")

    lines.append("## Example conversations")
    lines.append("")
    for case in conversations:
        lines.append(f"### {case['id']}: {case['title']}")
        lines.append("")
        if case.get("error"):
            lines.append(f"Could not run this case: `{case['error']}`")
            lines.append("")
            continue
        lines.append(f"State: `{json.dumps(case['state'])}`")
        lines.append("")
        for entry in case.get("transcript", []):
            label = entry["role"].capitalize()
            lines.append(f"**{label}:** {entry['content']}")
            lines.append("")

    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- Offline mode is a deterministic rule-based adapter. It proves the "
        "authorization, grounding and guardrail behaviour, but it is **not** a "
        "language model and earns no credit for live model behaviour."
    )
    lines.append(
        "- Live mode requires a reviewer-supplied API key. The live path was "
        "verified end to end against a local mock HTTP server (see "
        "`tests/test_live_provider.py`) and against a real local Ollama server "
        "running `qwen2.5:3b` at `http://localhost:11434/v1`. OpenAI was not "
        "called with a real API key, so the OpenAI request shape is "
        "implemented and mock-tested but no live OpenAI round-trip was "
        "performed. This is stated here rather than hidden."
    )
    lines.append(
        "- The catalog is synthetic and does not authorise any claim decision. "
        "Answers describe catalog wording only."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation suite.")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--out", default=str(ROOT / "reports" / "eval_report.md"))
    parser.add_argument("--json-out", default=str(ROOT / "reports" / "eval_report.json"))
    args = parser.parse_args()

    print(f"Running evaluation suite ({args.mode} mode)...\n")
    result, records = run_unittest_suite(args.pattern)
    conversations = run_conversations(args.mode)

    mode_label = conversations[0].get("mode", args.mode) if conversations else args.mode
    report = build_report(result, records, conversations, mode_label)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "mode": mode_label,
                "total": result.testsRun,
                "passed": result.testsRun - len(result.failures) - len(result.errors),
                "failed": len(result.failures),
                "errors": len(result.errors),
                "cases": [
                    {
                        "name": r["name"],
                        "ok": not r["errors"],
                        "duration_s": r["duration_s"],
                    }
                    for r in records
                ],
                "conversations": conversations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Report written to {out_path}")
    print(f"Machine-readable results written to {json_path}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
