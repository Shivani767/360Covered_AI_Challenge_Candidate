"""Ad-hoc probe for component-coverage guardrail edge cases (audit only)."""
import json
import sys

sys.path.insert(0, ".")

from coverage_assistant.catalog import Catalog
from coverage_assistant.facts import build_fact_pack, detect_intent
from coverage_assistant.guardrails import validate_answer
from coverage_assistant.state import normalize_state, resolve_referent

catalog = Catalog.load()


def check(answer, state, label):
    norm = normalize_state(state, catalog)
    intent = detect_intent("does it cover my engine")
    referent = resolve_referent("does it cover my engine", norm, catalog, [])
    fp = build_fact_pack("does it cover my engine", norm, referent, catalog, intent)
    res = validate_answer(answer, norm, catalog, fp)
    print(f"[{'PASS' if res.ok else 'REJECT'}] {label}")
    print(f"    answer: {answer!r}")
    for v in res.violations:
        print(f"    -> {v}")
    print()
    return res.ok


ALL = {
    "eligible_ids": ["P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"],
    "visible_ids": ["P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"],
    "selected_id": "P-BASE",
    "selected_options": [],
}
PLUS = {
    "eligible_ids": ["P-PLUS"],
    "visible_ids": ["P-PLUS"],
    "selected_id": "P-PLUS",
    "selected_options": [],
}
WRAP = {
    "eligible_ids": ["P-WRAP"],
    "visible_ids": ["P-WRAP"],
    "selected_id": "P-WRAP",
    "selected_options": [],
}
EXCL = {
    "eligible_ids": ["P-EXCL"],
    "visible_ids": ["P-EXCL"],
    "selected_id": "P-EXCL",
    "selected_options": [],
}

print("=" * 70)
print("T1: CoreDrive vs CoreDrive Plus")
print("=" * 70)
check("CoreDrive Plus covers the alternator. CoreDrive does not cover the alternator.", ALL, "Plus covers alternator, CoreDrive does not")
check("CoreDrive covers the alternator.", ALL, "CoreDrive claims alternator (should reject)")

print("=" * 70)
print("T2: multiple plans in one answer")
print("=" * 70)
check("CoreDrive covers the engine internal lubricated parts and CoreDrive Plus covers the alternator.", ALL, "two plans, both correct")
check("CoreDrive covers the alternator and CoreDrive Plus covers the alternator.", ALL, "CoreDrive claims alternator (should reject)")

print("=" * 70)
print("T3: exclusion then another plan's positive claim")
print("=" * 70)
check("DriveWrap does not cover the engine internal lubricated parts. CoreDrive covers the engine internal lubricated parts.", ALL, "wrap excludes, base covers")

print("=" * 70)
print("T4: negation within mixed clauses")
print("=" * 70)
check("The alternator is covered by CoreDrive Plus, but the starter motor is not covered.", PLUS, "mixed clause, neg")
check("The engine is not covered by DriveWrap.", WRAP, "negation only (should PASS)")

print("=" * 70)
print("T5: list context")
print("=" * 70)
check("CoreDrive Plus covers: engine internal lubricated parts, transmission internal lubricated parts, and brakes.", ALL, "list with brakes (should reject brakes)")
check("CoreDrive Plus covers: alternator, starter motor, and factory-installed radiator.", ALL, "list all valid (should PASS)")

print("=" * 70)
print("T6: aliases, incl. in exclusion statements")
print("=" * 70)
check("The engine is not covered by DriveWrap.", WRAP, "alias engine negation (PASS)")
check("DriveWrap covers the engine.", WRAP, "alias engine affirmative (reject)")

print("=" * 70)
print("T7/T8/T9: option purchase states")
print("=" * 70)
opt_purchased = {
    "eligible_ids": ["P-PLUS"],
    "visible_ids": ["P-PLUS"],
    "selected_id": "P-PLUS",
    "selected_options": ["electronics_plus"],
}
opt_not = {
    "eligible_ids": ["P-PLUS"],
    "visible_ids": ["P-PLUS"],
    "selected_id": "P-PLUS",
    "selected_options": [],
}
check("The factory-installed navigation screen is covered by the electronics_plus option you purchased.", opt_purchased, "option purchased (PASS)")
check("The navigation screen is covered by your electronics_plus option.", opt_purchased, "option purchased alias (PASS)")
check("The navigation screen is covered by CoreDrive Plus.", opt_not, "option not purchased (reject)")
check("The factory-installed navigation screen is covered by the electronics_plus option.", opt_not, "option not purchased (reject)")
check("The factory-installed catalytic converter is covered by the exhaust_plus option.", opt_not, "option-excluded? (reject)")

print("=" * 70)
print("T10: unknown / ambiguous components")
print("=" * 70)
check("The windshield is covered by CoreDrive Plus.", PLUS, "unknown component (expect PASS - no claim recognized)")
check("The turbocharger is covered by CoreDrive Plus.", PLUS, "unknown component 2")

print("=" * 70)
print("T11: punctuation / conjunctions / boundaries")
print("=" * 70)
check("CoreDrive Plus covers the alternator; CoreDrive Plus covers the starter motor.", PLUS, "semicolon")
check("CoreDrive Plus covers the alternator: it also covers the starter motor.", PLUS, "colon")
check("CoreDrive Plus covers the alternator and the starter motor and the radiator.", PLUS, "conjunction list (PASS)")
check("CoreDrive Plus covers the alternator. CoreDrive Plus covers the starter motor.", PLUS, "two sentences (PASS)")
check("CoreDrive Plus covers the alternator, and CoreDrive covers the engine.", ALL, "sentence with 2 plans")

print("=" * 70)
print("T12: no explicit plan attribution")
print("=" * 70)
check("The alternator is covered.", PLUS, "no plan named, single allowed (PASS)")
check("The alternator is covered.", ALL, "no plan named, multiple allowed")

print("=" * 70)
print("T13: broad plan (TotalDrive Select) - absence should NOT reject")
print("=" * 70)
check("TotalDrive Select covers the alternator.", EXCL, "broad plan, alternator (expect PASS)")
check("TotalDrive Select covers the engine.", EXCL, "broad plan, engine (expect PASS)")
check("TotalDrive Select covers the brake pads and brake rotors.", EXCL, "broad plan, brakes (should reject)")
