"""Ad-hoc probe 4: multi-plan clause attribution (audit only)."""
import sys

sys.path.insert(0, ".")

from coverage_assistant.catalog import Catalog
from coverage_assistant.facts import build_fact_pack, detect_intent
from coverage_assistant.guardrails import validate_answer
from coverage_assistant.state import normalize_state, resolve_referent

catalog = Catalog.load()

ALL = {
    "eligible_ids": ["P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"],
    "visible_ids": ["P-BASE", "P-PLUS", "P-WRAP", "P-EXCL"],
    "selected_id": "P-BASE",
    "selected_options": [],
}


def check(answer, label, state=ALL, q="tell me about my plans"):
    norm = normalize_state(state, catalog)
    intent = detect_intent(q)
    referent = resolve_referent(q, norm, catalog, [])
    fp = build_fact_pack(q, norm, referent, catalog, intent)
    res = validate_answer(answer, norm, catalog, fp)
    print(f"[{'PASS' if res.ok else 'REJECT'}] {label}")
    print(f"    {answer!r}")
    for v in res.violations:
        print(f"    -> {v}")
    print()
    return res.ok


print("### The suspected failing case")
check(
    "CoreDrive covers the alternator and CoreDrive Plus covers the alternator.",
    "WRONG: CoreDrive does NOT cover the alternator",
)
check("CoreDrive covers the alternator.", "single-plan: CoreDrive does NOT cover alternator")
check("CoreDrive Plus covers the alternator.", "single-plan: Plus DOES cover alternator")

print("### Coordination variants")
check(
    "CoreDrive covers the engine and CoreDrive Plus covers the alternator.",
    "both true, but CoreDrive+alternator false in first clause",
)
check(
    "CoreDrive and CoreDrive Plus cover the alternator.",
    "list form: CoreDrive does not cover alternator",
)
check(
    "CoreDrive Plus covers the alternator, while CoreDrive covers the engine.",
    "contrastive split: second clause false",
)
check(
    "DriveWrap covers the engine and CoreDrive Plus covers the alternator.",
    "DriveWrap explicitly excludes engine",
)
check(
    "CoreDrive Plus covers the alternator and DriveWrap covers the engine.",
    "DriveWrap explicitly excludes engine",
)
