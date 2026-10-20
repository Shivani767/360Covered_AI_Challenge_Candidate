"""Ad-hoc probe for malformed-output recovery (audit only)."""
import sys

sys.path.insert(0, ".")

from coverage_assistant import CoverageAssistant
from coverage_assistant.llm import BaseProvider, ProviderError

STATE = {
    "eligible_ids": ["P-PLUS"],
    "visible_ids": ["P-PLUS"],
    "selected_id": "P-PLUS",
    "selected_options": [],
}


class Fixed(BaseProvider):
    name = "fixed"
    is_llm = True

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages):
        self._check_budget()
        self.calls += 1
        r = self.responses.pop(0) if self.responses else ""
        if isinstance(r, Exception):
            raise r
        return r


print("=" * 70)
print("M1: empty string output")
print("=" * 70)
a = CoverageAssistant(provider=Fixed([""]))
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  violations:", t.violations, "repaired:", t.repaired, "fallback:", t.fallback_used)

print("=" * 70)
print("M2: whitespace-only output")
print("=" * 70)
a = CoverageAssistant(provider=Fixed(["   \n  "]))
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  violations:", t.violations, "repaired:", t.repaired, "fallback:", t.fallback_used)

print("=" * 70)
print("M3: non-string output (None)")
print("=" * 70)
a = CoverageAssistant(provider=Fixed([None]))
try:
    print(repr(a.answer("does it cover the alternator", STATE)))
except Exception as exc:
    print("  RAISED", type(exc).__name__, exc)

print("=" * 70)
print("M4: non-string output (dict)")
print("=" * 70)
a = CoverageAssistant(provider=Fixed([{"text": "hello"}]))
try:
    print(repr(a.answer("does it cover the alternator", STATE)))
except Exception as exc:
    print("  RAISED", type(exc).__name__, exc)

print("=" * 70)
print("M5: garbage / non-catalog text (should be rejected? or accepted?)")
print("=" * 70)
a = CoverageAssistant(provider=Fixed(["qwerty asdf zxcv"]))
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  violations:", t.violations, "repaired:", t.repaired, "fallback:", t.fallback_used)

print("=" * 70)
print("M6: model says 'I don't know'")
print("=" * 70)
a = CoverageAssistant(provider=Fixed(["I do not have that information."]))
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  violations:", t.violations, "repaired:", t.repaired, "fallback:", t.fallback_used)

print("=" * 70)
print("M7: repair attempt also malformed -> fallback")
print("=" * 70)
a = CoverageAssistant(provider=Fixed(["CoreDrive Plus covers everything."]))
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  violations:", t.violations, "repaired:", t.repaired, "fallback:", t.fallback_used)

print("=" * 70)
print("M8: provider raises ProviderError")
print("=" * 70)
a = CoverageAssistant(provider=Fixed([ProviderError("boom")]))
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  error:", t.error)

print("=" * 70)
print("M9: repair path succeeds (first bad, second good)")
print("=" * 70)
a = CoverageAssistant(
    provider=Fixed(["CoreDrive Plus covers the alternator.", "CoreDrive Plus covers the alternator."])
)
print(repr(a.answer("does it cover the alternator", STATE)))
t = a.last_trace
print("  violations:", t.violations, "repaired:", t.repaired, "fallback:", t.fallback_used)

print("=" * 70)
print("M10: extremely long output")
print("=" * 70)
a = CoverageAssistant(provider=Fixed(["CoreDrive Plus covers the alternator. " * 500]))
print(len(a.answer("does it cover the alternator", STATE)))

print("=" * 70)
print("M11: unicode / RTL / control chars")
print("=" * 70)
a = CoverageAssistant(provider=Fixed(["CoreDrive Plus covers the alternator.‮ \x00\x07"]))
print(repr(a.answer("does it cover the alternator", STATE)))
