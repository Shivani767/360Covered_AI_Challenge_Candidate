"""Broad sweep: many questions x many states, checked for safety properties.

This is a property-based style sweep rather than a set of fixed expectations.
It guards against the whole class of bugs where one state or one phrasing
slips through a rule that another state happened to satisfy.
"""
import unittest

from conftest_helper import ROOT  # noqa: F401
from coverage_assistant import CoverageAssistant
from coverage_assistant.catalog import Catalog
from coverage_assistant.facts import detect_universal_claim
from coverage_assistant.guardrails import (
    _mentions_blocked_plan,
    _only_in_refusal_context,
)

STATES = [
    {
        "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
        "visible_ids": ["P-BASE", "P-PLUS"],
        "selected_id": "P-PLUS",
        "selected_options": [],
    },
    {
        "eligible_ids": ["P-BASE", "P-WRAP"],
        "visible_ids": ["P-BASE", "P-WRAP"],
        "selected_id": "P-WRAP",
        "selected_options": [],
    },
    {
        "eligible_ids": ["P-EXCL"],
        "visible_ids": ["P-EXCL"],
        "selected_id": "P-EXCL",
        "selected_options": [],
    },
    {
        "eligible_ids": ["P-PLUS"],
        "visible_ids": ["P-PLUS"],
        "selected_id": "P-PLUS",
        "selected_options": ["electronics_plus"],
    },
    {
        "eligible_ids": [],
        "visible_ids": [],
        "selected_id": None,
        "selected_options": [],
    },
]

QUESTIONS = [
    "Is my navigation screen covered?",
    "Does this cover everything?",
    "What's the price?",
    "Tell me about TotalDrive Select",
    "What is the deductible for CoreDrive Plus?",
    "Will my claim be approved?",
    "Do I always get a rental car for 4 days?",
    "Is the engine covered?",
    "What about the catalytic converter?",
    "Compare all plans",
    "Does DriveWrap cover my engine?",
    "Is brake pads covered?",
    "Trip interruption?",
    "What is the most comprehensive plan you have?",
    "Tell me about P-GHOST",
    "What's excluded?",
    "Is everything covered including software updates?",
    "recommend the cheapest plan",
    "Is P-EXCL eligible for me?",
    "what is excluded from DriveWrap",
    "Can you approve my claim for the alternator?",
    "Does the navigation screen come with software updates?",
]


class SweepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def test_no_safety_property_is_violated_anywhere(self):
        problems = []
        for index, state in enumerate(STATES):
            bot = CoverageAssistant(mode="offline")
            allowed = set(state["eligible_ids"]) & set(state["visible_ids"])
            for question in QUESTIONS:
                answer = bot.answer(question, dict(state))
                body = answer.split("\n\n", 1)[-1]

                if detect_universal_claim(body):
                    problems.append((index, question, "universal coverage promise"))

                for plan_id in self.catalog.plan_ids():
                    if plan_id in allowed:
                        continue
                    if not _mentions_blocked_plan(body, plan_id, self.catalog):
                        continue
                    if not _only_in_refusal_context(body, plan_id, self.catalog):
                        problems.append((index, question, f"blocked plan leak: {plan_id}"))

                if bot.last_trace.violations:
                    problems.append(
                        (index, question, f"guardrail violations: {bot.last_trace.violations}")
                    )

        self.assertEqual(problems, [], f"problems found: {problems}")

    def test_every_answer_is_non_empty(self):
        for index, state in enumerate(STATES):
            bot = CoverageAssistant(mode="offline")
            for question in QUESTIONS:
                answer = bot.answer(question, dict(state))
                self.assertTrue(answer.strip(), f"empty answer for {question!r}")

    def test_every_answer_mentions_no_blocked_plan_price(self):
        """A blocked plan's price must never appear, not even in a refusal."""
        for state in STATES:
            bot = CoverageAssistant(mode="offline")
            allowed = set(state["eligible_ids"]) & set(state["visible_ids"])
            for question in QUESTIONS:
                answer = bot.answer(question, dict(state))
                for plan_id in self.catalog.plan_ids():
                    if plan_id in allowed:
                        continue
                    price = self.catalog.monthly_price(plan_id)
                    if price is None:
                        continue
                    self.assertNotIn(
                        f"${int(price)}",
                        answer,
                        f"price of blocked plan {plan_id} leaked for {question!r}",
                    )


if __name__ == "__main__":
    unittest.main()
