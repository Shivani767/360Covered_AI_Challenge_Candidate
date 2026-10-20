"""Multi-turn and state-change tests.

Covers the behaviour the brief calls out: a conversation must track state
changes between turns, and the assistant must not "stick" to a plan from an
earlier turn once the application state changes.
"""
import unittest

from conftest_helper import ROOT  # noqa: F401
from coverage_assistant import CoverageAssistant


def state(**kwargs):
    base = {
        "eligible_ids": ["P-BASE", "P-PLUS"],
        "visible_ids": ["P-BASE", "P-PLUS"],
        "selected_id": "P-BASE",
        "selected_options": [],
    }
    base.update(kwargs)
    return base


class MultiTurnTest(unittest.TestCase):
    def setUp(self):
        self.bot = CoverageAssistant(mode="offline")

    def test_selection_change_is_reflected_on_next_turn(self):
        first = self.bot.answer("Tell me about CoreDrive", state())
        self.assertIn("$200", first)  # P-BASE deductible

        second = self.bot.answer("What is its deductible?", state(selected_id="P-PLUS"))
        self.assertIn("$100", second)
        self.assertIn("P-PLUS", second)

    def test_plan_is_not_sticky_after_visibility_change(self):
        """A plan that becomes invisible must stop being discussed."""
        self.bot.answer("Tell me about CoreDrive Plus", state())
        answer = self.bot.answer(
            "What does it cover?",
            state(eligible_ids=["P-BASE"], visible_ids=["P-BASE"], selected_id="P-BASE"),
        )
        self.assertNotIn("P-PLUS", answer)
        self.assertNotIn("CoreDrive Plus", answer)

    def test_option_purchase_is_reflected(self):
        without = self.bot.answer("Is my navigation screen covered?", state())
        self.assertIn("not purchased", without.lower())

        with_option = self.bot.answer(
            "Is my navigation screen covered?",
            state(selected_options=["electronics_plus"]),
        )
        self.assertIn("covered", with_option.lower())
        self.assertNotIn("not purchased", with_option.lower())

    def test_option_removal_is_reflected(self):
        self.bot.answer(
            "Is my navigation screen covered?", state(selected_options=["electronics_plus"])
        )
        answer = self.bot.answer("Is my navigation screen covered?", state())
        self.assertIn("not purchased", answer.lower())

    def test_newly_visible_plan_can_be_discussed(self):
        answer = self.bot.answer(
            "Tell me about TotalDrive Select",
            state(
                eligible_ids=["P-BASE", "P-EXCL"],
                visible_ids=["P-BASE", "P-EXCL"],
                selected_id="P-EXCL",
            ),
        )
        self.assertIn("TotalDrive Select", answer)
        self.assertIn("$189", answer)

    def test_reset_clears_referent_memory(self):
        self.bot.answer("Tell me about CoreDrive Plus", state(selected_id="P-PLUS"))
        self.bot.reset()
        self.assertEqual(self.bot.history, [])
        self.assertEqual(self.bot.recent_plan_ids, [])
        answer = self.bot.answer(
            "What is its deductible?",
            state(selected_id="P-BASE"),
        )
        self.assertIn("$200", answer)

    def test_history_is_bounded(self):
        for index in range(30):
            self.bot.answer(f"Question number {index} about the plan", state())
        self.assertLessEqual(len(self.bot.history), 12)

    def test_conversation_does_not_drift_after_state_change(self):
        """Two turns, then the plan disappears from the allowed set."""
        self.bot.answer("Tell me about CoreDrive Plus", state())
        answer = self.bot.answer(
            "And its deductible?",
            state(eligible_ids=["P-BASE"], visible_ids=["P-BASE"], selected_id="P-BASE"),
        )
        self.assertNotIn("$100", answer)
        self.assertIn("$200", answer)


if __name__ == "__main__":
    unittest.main()
