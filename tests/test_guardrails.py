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


class ComponentCoverageClaimTest(unittest.TestCase):
    """A claim that a part is covered must never contradict the catalog.

    DriveWrap (P-WRAP) covers the alternator, starter motor and friends, and
    explicitly excludes the powertrain internals. An answer that tells the
    customer their engine is covered by DriveWrap is a false coverage claim
    and must be rejected, however it is phrased.
    """

    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def _check(self, answer, question="Does DriveWrap cover my engine?", state=None):
        state = state or {
            "eligible_ids": ["P-WRAP"],
            "visible_ids": ["P-WRAP"],
            "selected_id": "P-WRAP",
            "selected_options": [],
        }
        norm = normalize_state(state, self.catalog)
        intent = detect_intent(question)
        referent = resolve_referent(question, norm, self.catalog)
        fact_pack = build_fact_pack(question, norm, referent, self.catalog, intent)
        return validate_answer(answer, norm, self.catalog, fact_pack)

    # -- the original gap ---------------------------------------------
    def test_excluded_component_claim_is_rejected(self):
        result = self._check("Yes, the engine is covered by DriveWrap.")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("engine internal lubricated parts" in v for v in result.violations),
            result.violations,
        )

    def test_excluded_component_claim_by_plan_id_is_rejected(self):
        result = self._check("Yes, the engine is covered by P-WRAP.")
        self.assertFalse(result.ok)

    def test_exclusion_statement_is_allowed(self):
        result = self._check(
            "DriveWrap explicitly excludes the engine internal lubricated parts."
        )
        self.assertTrue(result.ok, result.violations)

    def test_negative_statement_is_allowed(self):
        result = self._check("The engine is not covered by DriveWrap.")
        self.assertTrue(result.ok, result.violations)

    # -- aliases ------------------------------------------------------
    def test_alias_based_excluded_claim_is_rejected(self):
        result = self._check("Yes, your engine is covered by DriveWrap.")
        self.assertFalse(result.ok)

    def test_alias_based_negative_is_allowed(self):
        result = self._check("Your transmission is not covered by DriveWrap.")
        self.assertTrue(result.ok, result.violations)

    def test_alias_based_covered_claim_is_allowed(self):
        result = self._check("Yes, your alternator is covered by DriveWrap.")
        self.assertTrue(result.ok, result.violations)

    # -- mixed clauses ------------------------------------------------
    def test_mixed_clauses_with_one_false_claim_are_rejected(self):
        result = self._check(
            "The engine is covered by DriveWrap, but the alternator is not covered."
        )
        self.assertFalse(result.ok)
        self.assertTrue(
            any("engine internal lubricated parts" in v for v in result.violations),
            result.violations,
        )

    def test_mixed_clauses_with_a_true_claim_are_allowed(self):
        result = self._check(
            "The alternator is covered by DriveWrap, but the engine is not covered "
            "by DriveWrap."
        )
        self.assertTrue(result.ok, result.violations)

    # -- exclusion / clause-scoped coverage -----------------------------

    def test_exclusion_clause_after_affirmative_clause_is_allowed(self):
        # The exclusion clause must not inherit the earlier coverage
        # assertion, so naming an excluded part as excluded is allowed.
        result = self._check(
            "DriveWrap covers the alternator and excludes the engine "
            "internal lubricated parts."
        )
        self.assertTrue(result.ok, result.violations)

    def test_exclusion_list_after_covered_list_is_allowed(self):
        result = self._check(
            "Coverage includes the alternator; exclusions include the engine "
            "internal lubricated parts."
        )
        self.assertTrue(result.ok, result.violations)

    def test_exclusion_bypass_is_rejected(self):
        # Dismissing an exclusion does not make an excluded part covered.
        for answer in [
            "Exclusions do not apply to your engine, so it is covered.",
            "Your engine is covered because the exclusion does not apply.",
            "The exclusion for the engine does not apply to you.",
            "Your engine is not excluded.",
            "Your engine is not excluded from coverage.",
            "Nothing excludes your engine, so it is covered.",
            "No exclusion applies to the engine under DriveWrap.",
            "The engine is covered by DriveWrap whenever the exclusion does "
            "not apply.",
        ]:
            with self.subTest(answer=answer):
                result = self._check(answer)
                self.assertFalse(result.ok, answer)
                self.assertTrue(
                    any("engine internal lubricated parts" in v for v in result.violations),
                    result.violations,
                )

    def test_conditional_coverage_claim_is_rejected(self):
        # "unless" is a condition, not a negation: the engine is still claimed
        # as covered by an excluding plan.
        result = self._check("The engine is covered by DriveWrap unless it is a worn part.")
        self.assertFalse(result.ok)

    def test_universal_part_coverage_claim_is_rejected(self):
        result = self._check("Every part is covered by DriveWrap.")
        self.assertFalse(result.ok)

    # -- plan attribution ---------------------------------------------
    def test_claim_attributed_to_the_plan_that_covers_it_is_allowed(self):
        result = self._check(
            "CoreDrive covers the engine internal lubricated parts.",
            state={
                "eligible_ids": ["P-BASE", "P-WRAP"],
                "visible_ids": ["P-BASE", "P-WRAP"],
                "selected_id": "P-WRAP",
                "selected_options": [],
            },
        )
        self.assertTrue(result.ok, result.violations)

    def test_claim_attributed_to_the_wrong_plan_is_rejected(self):
        result = self._check(
            "DriveWrap covers the engine internal lubricated parts.",
            state={
                "eligible_ids": ["P-BASE", "P-WRAP"],
                "visible_ids": ["P-BASE", "P-WRAP"],
                "selected_id": "P-WRAP",
                "selected_options": [],
            },
        )
        self.assertFalse(result.ok)

    def test_shorter_plan_name_inside_longer_name_is_not_attribution(self):
        """'CoreDrive Plus' must not be read as 'CoreDrive'."""
        result = self._check(
            "CoreDrive Plus covers the engine internal lubricated parts.",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertTrue(result.ok, result.violations)

    # -- options ------------------------------------------------------
    def test_option_covered_component_is_not_a_violation(self):
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

    def test_unpurchased_option_component_claim_is_rejected(self):
        result = self._check(
            "Yes, your navigation screen is covered.",
            question="Is my navigation screen covered?",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertFalse(result.ok)

    def test_option_excluded_component_claim_is_rejected(self):
        result = self._check(
            "Yes, software updates are covered by your plan.",
            question="Does the navigation screen come with software updates?",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": ["electronics_plus"],
            },
        )
        self.assertFalse(result.ok)

    def test_list_of_covered_components_is_allowed(self):
        """A list introduced by 'Covers' inherits the coverage assertion."""
        result = self._check(
            "DriveWrap covers: factory air-conditioning compressor, alternator, "
            "starter motor, factory-installed radiator, front suspension control arms."
        )
        self.assertTrue(result.ok, result.violations)



class MultiPlanAttributionAndMoneyTest(unittest.TestCase):
    """Cross-plan claims and money values must be attributed to the plan named.

    Regression coverage for:
      * substring/component-boundary matches ("engineer" != "engine"),
      * Base/Plus monetary misattribution ($139 is Plus, not Base),
      * coordinated multi-plan claims in a single sentence.
    """

    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def _check(self, answer, question="Tell me about my plans.", state=None):
        state = state or {
            "eligible_ids": ["P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"],
            "visible_ids": ["P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"],
            "selected_id": "P-BASE",
            "selected_options": [],
        }
        norm = normalize_state(state, self.catalog)
        intent = detect_intent(question)
        referent = resolve_referent(question, norm, self.catalog)
        fact_pack = build_fact_pack(question, norm, referent, self.catalog, intent)
        return validate_answer(answer, norm, self.catalog, fact_pack)

    # -- substring / word-boundary component matches --------------------
    def test_engineer_is_not_the_engine_component(self):
        result = self._check(
            "CoreDrive covers the engineer.",
            state={
                "eligible_ids": ["P-BASE", "P-WRAP"],
                "visible_ids": ["P-BASE", "P-WRAP"],
                "selected_id": "P-WRAP",
                "selected_options": [],
            },
        )
        self.assertTrue(result.ok, result.violations)

    def test_screening_is_not_the_navigation_screen(self):
        result = self._check(
            "CoreDrive Plus covers the screening.",
            state={
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
        )
        self.assertTrue(result.ok, result.violations)

    # -- Base / Plus monetary misattribution -----------------------------
    def test_base_price_misattributed_to_plus_is_rejected(self):
        result = self._check("CoreDrive is $139 per month.")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("139" in v and "CoreDrive" in v for v in result.violations),
            result.violations,
        )

    def test_base_deductible_misattributed_is_rejected(self):
        result = self._check("CoreDrive has a $100 deductible.")
        self.assertFalse(result.ok)

    def test_base_correct_price_and_deductible_allowed(self):
        result = self._check("CoreDrive is $89 per month with a $200 deductible.")
        self.assertTrue(result.ok, result.violations)

    # -- coordinated multi-plan claims -----------------------------------
    def test_multiplan_false_first_clause_is_rejected(self):
        result = self._check(
            "CoreDrive covers the alternator and CoreDrive Plus covers the alternator."
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("CoreDrive" in v for v in result.violations), result.violations)

    def test_multiplan_both_true_is_allowed(self):
        result = self._check(
            "CoreDrive covers the engine and CoreDrive Plus covers the alternator."
        )
        self.assertTrue(result.ok, result.violations)

    def test_multiplan_wrap_engine_excluded_is_rejected(self):
        result = self._check(
            "DriveWrap covers the engine and CoreDrive Plus covers the alternator."
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("DriveWrap" in v for v in result.violations), result.violations)


if __name__ == "__main__":
    unittest.main()
