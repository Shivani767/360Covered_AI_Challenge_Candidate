"""Guardrails: authorization before generation, validation after generation.

Two halves, both in code (never only in the prompt):

**Pre-generation (authorization).** `authorized_scope` decides which plans
may appear in the response at all. If the customer names a plan that is not
in ``eligible AND visible``, the response is allowed to say that the
plan is not available to them and nothing else. It may not repeat its
price, components, or deductible.

**Post-generation (validation).** `validate_answer` re-reads the model's
output and checks it against the fact pack. It looks for:
  * universal coverage promises ("covers everything"),
  * plan ids or names outside the authorized set,
  * prices, deductibles and benefit amounts that do not match the catalog,
  * claiming an unpurchased option is in force,
  * guaranteed benefit language (e.g. "always a rental car for 4 days"),
  * claims-decision language ("your claim is approved").

A violation triggers a repair attempt, and if that still fails, the answer
is replaced with a deterministic, catalog-derived response. The model never
has the last word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .catalog import Catalog
from .facts import detect_universal_claim
from .state import NormalizedState

# Guarantee-style phrases that must not be used for conditional benefits.
GUARANTEE_PHRASES = [
    "always a rental",
    "always get a rental",
    "always get rental",
    "guaranteed rental",
    "guaranteed to be covered",
    "guaranteed coverage",
    "is guaranteed",
    "will be covered no matter",
    "no matter what",
    "for sure you will",
    "automatically approved",
    "claim is approved",
    "claim will be approved",
    "will be approved",
    "you will be reimbursed",
    "definitely covered",
    "certainly covered",
]

# Markers that negate a coverage assertion within the same sentence.
NEGATIVE_MARKERS = [
    "not covered",
    "isn't covered",
    "is not covered",
    "not include",
    "not included",
    "would not",
    "wouldn't",
    "does not",
    "doesn't",
    "unless",
    "only if",
    "not purchased",
    "have not purchased",
    "has not purchased",
    "haven't purchased",
    "not currently",
    "not in force",
    "not active",
    "no electronics",
    "would require",
    "requires",
    "not available",
    "cannot",
    "can't",
    "without purchasing",
    "not yet",
]

# Markers that indicate a statement of unavailability or refusal. A blocked
# plan may only be named in a sentence containing one of these.
REFUSAL_MARKERS = [
    "not available",
    "not currently",
    "not eligible",
    "not visible",
    "unavailable",
    "cannot",
    "can't",
    "can not",
    "do not",
    "don't",
    "does not",
    "doesn't",
    "is not",
    "isn't",
    "no longer",
    "unable",
    "outside",
    "not something",
    "not one of",
    "not among",
    "not offered",
    "not included",
    "cannot describe",
    "cannot offer",
    "cannot recommend",
    "not recommend",
    "not suggest",
]

# Markers that assert coverage within the same sentence.
POSITIVE_MARKERS = [
    "is covered",
    "are covered",
    "covers",
    "covered under",
    "you are covered",
    "you're covered",
    "will be covered",
    "is included",
    "includes",
]


@dataclass
class GuardrailResult:
    """Outcome of validating a candidate answer."""

    ok: bool
    violations: List[str] = field(default_factory=list)
    repaired: bool = False
    fallback_used: bool = False
    answer: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": list(self.violations),
            "repaired": self.repaired,
            "fallback_used": self.fallback_used,
        }


# ----------------------------------------------------------------------
# pre-generation authorization
# ----------------------------------------------------------------------
def authorized_scope(state: NormalizedState, catalog: Catalog) -> Dict[str, Any]:
    """Plans and details the assistant is permitted to talk about."""
    allowed = catalog.ordered_ids(state.allowed_ids)
    return {
        "allowed_plan_ids": allowed,
        "allowed_plan_names": [catalog.plan_name(pid) for pid in allowed],
        # Every plan id in the catalog, so the validator can detect leaks.
        "all_plan_ids": catalog.plan_ids(),
        "all_plan_names": [catalog.plan_name(pid) for pid in catalog.plan_ids()],
        "allowed_prices": {
            pid: catalog.monthly_price(pid) for pid in allowed if catalog.monthly_price(pid) is not None
        },
        "allowed_deductibles": {
            pid: catalog.deductible(pid) for pid in allowed if catalog.deductible(pid) is not None
        },
    }


# ----------------------------------------------------------------------
# post-generation validation
# ----------------------------------------------------------------------
def _money_values(text: str) -> List[float]:
    """All dollar amounts in a text, normalised to floats."""
    values: List[float] = []
    for match in re.finditer(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    for match in re.finditer(r"\b([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:dollars|usd|bucks)\b", text.lower()):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return values


def _normalize_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _asserts_coverage(answer: str, subject: str) -> bool:
    """Heuristic: does a sentence containing `subject` assert coverage?

    Evaluated sentence by sentence so that "the navigation screen is covered
    by the electronics_plus option, which you have not purchased" is not
    treated the same as "your navigation screen is covered".
    """
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        if subject.lower() not in sentence.lower():
            continue
        sent = sentence.lower()
        if any(marker in sent for marker in NEGATIVE_MARKERS):
            continue
        if any(pos in sent for pos in POSITIVE_MARKERS):
            return True
    return False


def _mentions_blocked_plan(answer: str, plan_id: str, catalog: Catalog) -> bool:
    """True when the answer names a plan the customer may not see.

    Word-boundary aware, and a shorter plan name that is a substring of a
    longer one does not count: "CoreDrive" inside "CoreDrive Plus" is not
    a mention of the shorter plan.
    """
    if re.search(rf"\b{re.escape(plan_id)}\b", answer):
        return True
    name = catalog.plan_name(plan_id)
    if not name:
        return False
    lowered = answer.lower()
    if name.lower() not in lowered:
        return False
    for other_id in catalog.plan_ids():
        if other_id == plan_id:
            continue
        other = catalog.plan_name(other_id)
        if not other or other.lower() == name.lower():
            continue
        if name.lower() in other.lower() and other.lower() in lowered:
            return False
    return True


def _only_in_refusal_context(answer: str, plan_id: str, catalog: Catalog) -> bool:
    """True when every mention of a blocked plan is a statement of unavailability."""
    name = catalog.plan_name(plan_id)
    tokens = [t for t in (plan_id, name) if t]
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        sent = sentence.lower()
        if not any(token.lower() in sent for token in tokens):
            continue
        if not any(marker in sent for marker in REFUSAL_MARKERS):
            return False
    return True


def validate_answer(
    answer: str,
    state: NormalizedState,
    catalog: Catalog,
    fact_pack: Dict[str, Any],
) -> GuardrailResult:
    """Check a candidate answer against the authorized scope and the catalog."""
    violations: List[str] = []
    if not isinstance(answer, str) or not answer.strip():
        return GuardrailResult(ok=False, violations=["Empty answer."], answer=answer or "")

    lowered = answer.lower()

    # 1. universal coverage promise
    if detect_universal_claim(answer):
        violations.append("Unqualified universal coverage promise.")

    # 2. guarantee / claims-decision language
    for phrase in GUARANTEE_PHRASES:
        if phrase in lowered:
            violations.append(f"Guarantee/claims-decision language: '{phrase}'.")
            break

    # 3. mention of unauthorized plan ids or names.
    #
    # Naming a blocked plan is allowed only as a refusal: the brief says a
    # customer may ask about a plan they cannot see, and the answer should
    # say it is unavailable. What is never allowed is describing that plan.
    # The second loop below blocks the *details*.
    allowed_ids = set(state.allowed_ids)
    for plan_id in catalog.plan_ids():
        if plan_id in allowed_ids:
            continue
        if not _mentions_blocked_plan(answer, plan_id, catalog):
            continue
        if not _only_in_refusal_context(answer, plan_id, catalog):
            name = catalog.plan_name(plan_id)
            violations.append(
                f"Unauthorized plan referenced without a refusal: {plan_id} ({name})."
            )

    # 4. money values must be attributable to an allowed plan or a benefit
    allowed_amounts = set()
    blocked_amounts = set()
    for value in fact_pack.get("allowed_plans", []):
        for key in ("monthly_price", "deductible"):
            amount = _normalize_money(value.get(key))
            if amount is not None:
                allowed_amounts.add(amount)
    for benefit in fact_pack.get("benefits", {}).values():
        for key, amount in benefit.items():
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                allowed_amounts.add(float(amount))
    # Amounts belonging only to a blocked plan are not attributable either.
    blocked_plan_ids = set(fact_pack.get("blocked_plan_ids", []))
    for plan_id in blocked_plan_ids:
        for key in ("monthly_price", "deductible"):
            amount = _normalize_money(catalog.plan_facts(plan_id).get(key))
            if amount is not None:
                blocked_amounts.add(amount)
    for amount in _money_values(answer):
        if amount in blocked_amounts and amount not in allowed_amounts:
            violations.append(
                f"Amount ${amount:g} belongs to a plan that is not available to the customer."
            )
        elif amount not in allowed_amounts:
            violations.append(f"Amount ${amount:g} does not match the catalog.")

    # 5. option coverage without purchase
    purchased = set(fact_pack.get("purchased_options", []))
    for option in fact_pack.get("option_status", []):
        if option["purchased"]:
            continue
        for covered in option["covers"]:
            if covered.lower() in lowered:
                if _asserts_coverage(answer, covered):
                    violations.append(
                        f"Answer implies '{covered}' is covered without purchased option "
                        f"'{option['id']}'."
                    )
                break

    # 6. deductible correctness for the plan in question
    referent = fact_pack.get("referent_plan")
    if referent:
        deductible = _normalize_money(referent.get("deductible"))
        if deductible is not None and "deductible" in lowered:
            mentioned = _money_values(answer)
            if mentioned and deductible not in mentioned:
                violations.append(
                    f"Deductible stated does not match catalog value ${deductible:g}."
                )

    return GuardrailResult(ok=not violations, violations=violations, answer=answer)
