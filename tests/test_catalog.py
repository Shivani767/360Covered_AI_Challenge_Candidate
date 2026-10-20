"""Catalog resolution tests: inheritance, exclusions, option facts."""
import unittest

from conftest_helper import ROOT  # noqa: F401  (adds project root to sys.path)
from coverage_assistant.catalog import Catalog


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def test_all_plans_loaded(self):
        self.assertEqual(
            sorted(self.catalog.plan_ids()),
            ["P-BASE", "P-EXCL", "P-PLUS", "P-WRAP"],
        )

    def test_plus_inherits_base(self):
        self.assertTrue(self.catalog.inherits_from("P-PLUS", "P-BASE"))
        components = self.catalog.components("P-PLUS")["items"]
        self.assertIn("engine internal lubricated parts", components)
        self.assertIn("alternator", components)

    def test_wrap_does_not_inherit_base(self):
        """The Wrap plan must not inherit powertrain coverage."""
        self.assertFalse(self.catalog.inherits_from("P-WRAP", "P-BASE"))
        components = self.catalog.components("P-WRAP")["items"]
        self.assertNotIn("engine internal lubricated parts", components)
        self.assertNotIn("transmission internal lubricated parts", components)
        self.assertNotIn("drive axle internal parts", components)
        self.assertIn("alternator", components)

    def test_wrap_explicitly_excludes_powertrain(self):
        excluded = self.catalog.explicitly_excluded_components("P-WRAP")
        self.assertIn("engine internal lubricated parts", excluded)

    def test_exclusionary_plan_is_broad(self):
        components = self.catalog.components("P-EXCL")
        self.assertTrue(components["broad"])
        self.assertIsInstance(self.catalog.exclusions("P-EXCL"), list)
        self.assertIn("brake pads and brake rotors", self.catalog.exclusions("P-EXCL"))

    def test_prices_and_deductibles_match_catalog(self):
        self.assertEqual(self.catalog.monthly_price("P-BASE"), 89)
        self.assertEqual(self.catalog.monthly_price("P-PLUS"), 139)
        self.assertEqual(self.catalog.monthly_price("P-WRAP"), 109)
        self.assertEqual(self.catalog.monthly_price("P-EXCL"), 189)
        self.assertEqual(self.catalog.deductible("P-BASE"), 200)
        self.assertEqual(self.catalog.deductible("P-PLUS"), 100)
        self.assertEqual(self.catalog.deductible("P-WRAP"), 100)
        self.assertEqual(self.catalog.deductible("P-EXCL"), 100)

    def test_ordered_ids_uses_catalog_comparison_order(self):
        ordered = self.catalog.ordered_ids(["P-EXCL", "P-WRAP", "P-BASE", "P-PLUS"])
        self.assertEqual(ordered, ["P-BASE", "P-PLUS", "P-EXCL", "P-WRAP"])

    def test_option_facts(self):
        facts = self.catalog.option_facts("electronics_plus")
        self.assertIn("factory-installed navigation screen", facts["covers"])
        self.assertIn("software updates", facts["excludes"])

    def test_unknown_plan_returns_empty_facts(self):
        self.assertEqual(self.catalog.plan_facts("P-NOPE"), {})

    def test_benefits_present(self):
        rental = self.catalog.benefit("rental")
        self.assertEqual(rental["daily_cap_usd"], 30)
        self.assertEqual(rental["max_days"], 4)
        trip = self.catalog.benefit("trip_interruption")
        self.assertEqual(trip["daily_cap_usd"], 90)
        self.assertEqual(trip["max_days"], 3)


if __name__ == "__main__":
    unittest.main()
