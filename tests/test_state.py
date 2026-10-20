"""State normalization, authorization and referent resolution tests."""
import unittest

from conftest_helper import ROOT  # noqa: F401
from coverage_assistant.catalog import Catalog
from coverage_assistant.state import (
    match_option_id,
    normalize_state,
    resolve_referent,
)


class StateNormalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def test_allowed_is_intersection_not_union(self):
        state = normalize_state(
            {
                "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
                "visible_ids": ["P-BASE", "P-PLUS"],
                "selected_id": "P-PLUS",
                "selected_options": [],
            },
            self.catalog,
        )
        self.assertEqual(state.allowed_ids, ["P-BASE", "P-PLUS"])
        self.assertNotIn("P-EXCL", state.allowed_ids)

    def test_missing_visible_ids_does_not_widen_to_whole_catalog(self):
        """Regression test for the starter bug: the default must not be 'all plans'."""
        state = normalize_state({"eligible_ids": ["P-BASE"]}, self.catalog)
        self.assertEqual(state.allowed_ids, [])

    def test_missing_eligible_ids_does_not_widen(self):
        state = normalize_state({"visible_ids": ["P-BASE", "P-PLUS"]}, self.catalog)
        self.assertEqual(state.allowed_ids, [])

    def test_unknown_plan_ids_are_dropped_with_warning(self):
        state = normalize_state(
            {"eligible_ids": ["P-BASE", "P-GHOST"], "visible_ids": ["P-BASE"]},
            self.catalog,
        )
        self.assertEqual(state.allowed_ids, ["P-BASE"])
        self.assertTrue(any("P-GHOST" in w for w in state.warnings))

    def test_malformed_state_does_not_raise(self):
        for bad in [None, 42, "nonsense", [], {"eligible_ids": 5}, {"visible_ids": {"a": 1}}]:
            state = normalize_state(bad, self.catalog)
            self.assertEqual(state.allowed_ids, [])

    def test_unknown_option_is_dropped(self):
        state = normalize_state(
            {
                "eligible_ids": ["P-BASE"],
                "visible_ids": ["P-BASE"],
                "selected_options": ["electronics_plus", "not_a_real_option"],
            },
            self.catalog,
        )
        self.assertEqual(state.selected_options, ["electronics_plus"])

    def test_empty_eligible_list_is_handled(self):
        state = normalize_state(
            {"eligible_ids": [], "visible_ids": [], "selected_id": None},
            self.catalog,
        )
        self.assertEqual(state.allowed_ids, [])


class ReferentResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def _state(self, **kwargs):
        base = {
            "eligible_ids": ["P-BASE", "P-PLUS"],
            "visible_ids": ["P-BASE", "P-PLUS"],
            "selected_id": "P-BASE",
            "selected_options": [],
        }
        base.update(kwargs)
        return normalize_state(base, self.catalog)

    def test_explicit_plan_name_wins(self):
        ref = resolve_referent("Tell me about CoreDrive", self._state(), self.catalog)
        self.assertEqual(ref.plan_id, "P-BASE")
        self.assertEqual(ref.source, "explicit")

    def test_selection_wins_over_stale_recent(self):
        """A selection change is an event, not a suggestion."""
        state = self._state(selected_id="P-PLUS")
        ref = resolve_referent(
            "What is its deductible?", state, self.catalog, recent_plan_ids=["P-BASE"]
        )
        self.assertEqual(ref.plan_id, "P-PLUS")
        self.assertEqual(ref.source, "selected")

    def test_recent_used_when_no_selection(self):
        state = self._state(selected_id=None)
        ref = resolve_referent(
            "What is its deductible?", state, self.catalog, recent_plan_ids=["P-PLUS"]
        )
        self.assertEqual(ref.plan_id, "P-PLUS")
        self.assertEqual(ref.source, "recent")

    def test_only_allowed_plan_is_used_as_last_resort(self):
        state = normalize_state(
            {
                "eligible_ids": ["P-PLUS"],
                "visible_ids": ["P-PLUS"],
                "selected_id": None,
                "selected_options": [],
            },
            self.catalog,
        )
        ref = resolve_referent("What is the deductible?", state, self.catalog)
        self.assertEqual(ref.plan_id, "P-PLUS")

    def test_named_but_unavailable_plan_is_not_resolved(self):
        state = self._state()
        ref = resolve_referent("Tell me about DriveWrap", state, self.catalog)
        self.assertNotEqual(ref.plan_id, "P-WRAP")
        self.assertIn("P-WRAP", ref.mentioned_ids)

    def test_longer_plan_name_wins(self):
        """'CoreDrive Plus' must not also count as a mention of 'CoreDrive'."""
        state = self._state(selected_id=None)
        ref = resolve_referent("Tell me about CoreDrive Plus", state, self.catalog)
        self.assertEqual(ref.plan_id, "P-PLUS")
        self.assertNotIn("P-BASE", ref.mentioned_ids)

    def test_shorter_plan_name_still_matches(self):
        state = self._state(selected_id=None)
        ref = resolve_referent("Tell me about CoreDrive", state, self.catalog)
        self.assertEqual(ref.plan_id, "P-BASE")

    def test_option_id_matching(self):
        self.assertEqual(
            match_option_id("can I add electronics_plus", self.catalog), "electronics_plus"
        )
        self.assertEqual(
            match_option_id("what about the navigation screen", self.catalog),
            "electronics_plus",
        )
        self.assertIsNone(match_option_id("nothing relevant", self.catalog))


if __name__ == "__main__":
    unittest.main()
