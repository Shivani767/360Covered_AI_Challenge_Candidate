"""End-to-end scenario tests against the supplied data/scenarios.json.

Each supplied scenario is replayed through the real assistant in offline
mode and checked with deterministic assertions. These are the "acceptance"
behaviours from the assessment brief.
"""
import unittest

from conftest_helper import load_scenarios, strip_label  # noqa: F401
from coverage_assistant import CoverageAssistant
from coverage_assistant.facts import detect_universal_claim


class ScenarioTest(unittest.TestCase):
    """Replays data/scenarios.json."""

    def test_all_scenarios_meet_expectation(self):
        for scenario in load_scenarios():
            with self.subTest(scenario=scenario["id"], desc=scenario["description"]):
                bot = CoverageAssistant(mode="offline")
                state = dict(scenario["state"])
                answers = []

                events = scenario.get("events")
                if events:
                    for event in events:
                        if event["kind"] == "ask":
                            answers.append(bot.answer(event["value"], state))
                        elif event["kind"] == "select":
                            state["selected_id"] = event["value"]
                else:
                    for turn in scenario["turns"]:
                        answers.append(bot.answer(turn, state))

                self._assert_scenario(scenario, answers)

    def _assert_scenario(self, scenario, answers):
        sid = scenario["id"]
        text = " ".join(strip_label(a) for a in answers)

        if sid == "S1":
            # Only the visible plans may be compared or recommended.
            self.assertNotIn("P-EXCL", text)
            self.assertNotIn("TotalDrive Select", text)
            self.assertIn("P-BASE", text)
            self.assertIn("P-PLUS", text)

        elif sid == "S2":
            # No blanket promise; brake pads must be explained as excluded.
            lowered = text.lower()
            self.assertFalse(
                detect_universal_claim(text),
                "answer makes an unqualified universal coverage promise",
            )
            self.assertNotIn("covers everything", lowered)
            self.assertNotIn("covers all", lowered)
            self.assertNotIn("bumper to bumper", lowered)
            self.assertIn("brake pads and brake rotors", lowered)

        elif sid == "S3":
            # The selection change must be reflected: $100 for P-PLUS.
            self.assertIn("$100", answers[-1])
            self.assertIn("P-PLUS", answers[-1])

        elif sid == "S4":
            # Navigation screen is offered but not purchased.
            lowered = text.lower()
            self.assertIn("electronics_plus", lowered)
            self.assertTrue(
                "not purchased" in lowered or "not in force" in lowered
                or "not currently covered" in lowered,
                lowered,
            )

        elif sid == "S5":
            # Wrap must not inherit powertrain.
            lowered = text.lower()
            self.assertIn("engine internal lubricated parts", lowered)
            self.assertTrue("not covered" in lowered or "excluded" in lowered)
            self.assertNotIn("transmission internal lubricated parts", lowered)

        elif sid == "S6":
            # Rental is conditional, $30/day, 4 days max.
            lowered = text.lower()
            self.assertIn("$30", text)
            self.assertIn("4 days", lowered)
            self.assertTrue(
                "not automatic" in lowered
                or "only when" in lowered
                or "conditions" in lowered,
                lowered,
            )
            self.assertNotIn("always get a rental", lowered)


class ScenarioTraceTest(unittest.TestCase):
    """Checks the internal trace, not just the text."""

    def test_trace_records_authorization_scope(self):
        bot = CoverageAssistant(mode="offline")
        bot.answer(
            "Which plan is best?",
            {
                "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        trace = bot.last_trace
        self.assertEqual(trace.allowed_plan_ids, ["P-BASE", "P-PLUS"])
        self.assertEqual(trace.violations, [])

    def test_offline_mode_is_labelled_not_llm(self):
        bot = CoverageAssistant(mode="offline")
        answer = bot.answer("Tell me about the plan", {
            "eligible_ids": ["P-BASE"],
            "visible_ids": ["P-BASE"],
            "selected_id": "P-BASE",
            "selected_options": [],
        })
        self.assertIn("OFFLINE_DETERMINISTIC", answer)
        self.assertFalse(bot.is_live_llm)


if __name__ == "__main__":
    unittest.main()
