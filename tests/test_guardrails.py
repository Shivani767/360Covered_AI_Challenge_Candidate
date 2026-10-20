"""Guardrail tests: the validator must catch unsafe model output.

These tests feed *deliberately unsafe* candidate answers to the validator
directly, so they prove the code-level check works regardless of which
model produced the text.
"""
import unittest

from conftest_helper import ROOT  # noqa: F401
from coverage_assistant.catalog import Catalog
from coverage_assistant.facts import build_fact_pack, detect_intent
from coverage_assistant.guardrails import authorized_scope, validate_answer
from coverage_assistant.state import normalize_state, resolve_referent


class GuardrailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def _check(self, answer, question="What does this cover?", state=None):
        state = state or {
            "eligible_ids": ["P-BASE", "P-PLUS"],
            "visible_ids": ["P-BASE", "P-PLUS"],
            "selected_id": "P-PLUS",
            "selected_options": [],
        }
        norm = normalize_state(state, self.catalog)
        intent = detect_intent(question)
        referent = resolve_referent(question, norm, self.catalog)
        fact_pack = build_fact_pack(question, norm, referent, self.catalog, intent)
        return validate_answer(answer, norm, self.catalog, fact_pack)

    # -- universal promises -------------------------------------------
    def test_universal_promise_is_rejected(self):
        result = self._check("This plan covers everything you ask about.")
        self.assertFalse(result.ok)
        self.assertTrue(any("universal" in v.lower() for v in result.violations))

    def test_bumper_to_bumper_claim_rejected(self):
        result = self._check("You get bumper to bumper coverage with no exclusions.")
        self.assertFalse(result.ok)

    # -- invisible plan leakage ---------------------------------------
    def test_unauthorized_plan_id_rejected(self):
        result = self._check("P-EXCL is a great choice for you.")
        self.assertFalse(result.ok)
        self.assertTrue(any("P-EXCL" in v for v in result.violations))

    def test_unauthorized_plan_name_rejected(self):
        result = self._check("TotalDrive Select would be the best option.")
        self.assertFalse(result.ok)
        self.assertTrue(any("TotalDrive Select" in v for v in result.violations))

    def test_authorized_plan_id_allowed(self):
        result = self._check("P-PLUS has a $100 deductible and costs $139 per month.")
        self.assertTrue(result.ok, result.violations)

    # -- fabricated numbers -------------------------------------------
    def test_fabricated_price_rejected(self):
        result = self._check("P-BASE is $49 per month.")
        self.assertFalse(result.ok)
        self.assertTrue(any("does not match" in v for v in result.violations))

    def test_fabricated_deductible_rejected(self):
        result = self._check("The deductible for P-PLUS is $500.")
        self.assertFalse(result.ok)

    def test_correct_price_and_deductible_allowed(self):
        result = self._check(
            "CoreDrive Plus (P-PLUS) is $139 per month with a $100 deductible."
        )
        self.assertTrue(result.ok, result.violations)

    # -- option status ------------------------------------------------
    def test_unpurchased_option_coverage_rejected(self):
        result = self._check(
            "Your factory-installed navigation screen is covered.",
            question="Is my navigation screen covered?",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertFalse(result.ok)

    def test_unpurchased_option_with_hedge_allowed(self):
        result = self._check(
            "The factory-installed navigation screen would be covered by the "
            "electronics_plus option, which you have not purchased, so it is not "
            "currently covered.",
            question="Is my navigation screen covered?",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertTrue(result.ok, result.violations)

    def test_purchased_option_coverage_allowed(self):
        result = self._check(
            "Your factory-installed navigation screen is covered by the "
            "electronics_plus option.",
            question="Is my navigation screen covered?",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": ["electronics_plus"],
            },
        )
        self.assertTrue(result.ok, result.violations)

    # -- guarantees and claims decisions ------------------------------
    def test_guaranteed_rental_rejected(self):
        result = self._check(
            "You always get a rental car for four days.",
            question="Do I always get a rental car for four days?",
        )
        self.assertFalse(result.ok)

    def test_claim_approval_rejected(self):
        result = self._check(
            "Your claim will be approved and you will be reimbursed.",
            question="Will my claim be approved?",
        )
        self.assertFalse(result.ok)

    def test_conditional_benefit_allowed(self):
        result = self._check(
            "Rental reimbursement is up to $30 per day for a maximum of 4 days, "
            "and only when the conditions are met.",
            question="Do I always get a rental car for four days?",
        )
        self.assertTrue(result.ok, result.violations)

    # -- misc ---------------------------------------------------------
    def test_empty_answer_rejected(self):
        result = self._check("   ")
        self.assertFalse(result.ok)

    def test_shorter_plan_name_inside_longer_is_not_a_violation(self):
        """'CoreDrive Plus' must not be read as a mention of 'CoreDrive'."""
        result = self._check("CoreDrive Plus (P-PLUS) has a $100 deductible.")
        self.assertTrue(result.ok, result.violations)

    def test_authorized_scope_lists_all_catalog_ids(self):
        norm = normalize_state(
            {"eligible_ids": ["P-BASE"], "visible_ids": ["P-BASE"]}, self.catalog
        )
        scope = authorized_scope(norm, self.catalog)
        self.assertEqual(scope["allowed_plan_ids"], ["P-BASE"])
        self.assertIn("P-EXCL", scope["all_plan_ids"])


if __name__ == "__main__":
    unittest.main()
