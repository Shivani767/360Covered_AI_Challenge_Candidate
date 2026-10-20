"""Ad-hoc probe 3: price attribution, alias substrings, misc (audit only)."""
import sys

sys.path.insert(0, ".")

from coverage_assistant.catalog import Catalog
from coverage_assistant.facts import build_fact_pack, detect_intent, mentioned_components
from coverage_assistant.guardrails import validate_answer
from coverage_assistant.state import normalize_state, resolve_referent

catalog = Catalog.load()


def check(answer, state, label, q="tell me about my plan"):
    norm = normalize_state(state, catalog)
    intent = detect_intent(q)
    referent = resolve_referent(q, norm, catalog, [])
    fp = build_fact_pack(q, norm, referent, catalog, intent)
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

print("=" * 70)
print("D2: price misattribution between allowed plans")
print("=" * 70)
check("CoreDrive Plus costs $89 per month.", ALL, "Plus priced at Base price ($89) - WRONG")
check("CoreDrive costs $139 per month.", ALL, "Base priced at Plus price ($139) - WRONG")
check("CoreDrive costs $89 per month.", ALL, "Base correct price (PASS)")
check("CoreDrive Plus costs $139 per month.", ALL, "Plus correct price (PASS)")
check("CoreDrive costs $109 per month.", ALL, "Base priced at DriveWrap price - WRONG")

print("=" * 70)
print("D2b: deductible misattribution")
print("=" * 70)
check("CoreDrive Plus has a $200 deductible.", PLUS, "Plus deductible wrong (200 = base) - WRONG")
check("CoreDrive Plus has a $100 deductible.", PLUS, "Plus deductible correct (PASS)")

print("=" * 70)
print("D3: alias substring matching")
print("=" * 70)
for text in [
    "The engineer is covered by CoreDrive Plus.",
    "Our screening process is covered.",
    "The engineer's report is covered by CoreDrive.",
    "The starter pack is covered.",
]:
    print(f"  {text!r} -> {mentioned_components(text, catalog)}")

print()
check("The engineer is covered by CoreDrive Plus.", PLUS, "engineer (substring of engine)")
check("Our screening process is covered by CoreDrive Plus.", PLUS, "screening (substring of screen)")

print("=" * 70)
print("D3b: alias matches inside longer words generally")
print("=" * 70)
for text in [
    "The gearbox assembly is covered.",
    "The differential is covered.",
    "The catalytic converter is covered.",
    "The camera works.",
    "The radar is covered.",
]:
    print(f"  {text!r} -> {mentioned_components(text, catalog)}")
