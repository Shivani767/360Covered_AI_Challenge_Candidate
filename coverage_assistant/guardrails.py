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
  * claims-decision language ("your claim is approved"),
  * claiming that a part the plan in question excludes is covered
    (e.g. "yes, the engine is covered by DriveWrap").

A violation triggers a repair attempt, and if that still fails, the answer
is replaced with a deterministic, catalog-derived response. The model never
has the last word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .catalog import Catalog
from .facts import COMPONENT_ALIASES, detect_universal_claim, mentioned_component_spans, mentioned_components
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


def _asserts_coverage(answer: str, subject: str, aliases: Optional[List[str]] = None) -> bool:
    """Heuristic: does a sentence containing `subject` assert coverage?

    Evaluated sentence by sentence so that "the navigation screen is covered
    by the electronics_plus option, which you have not purchased" is not
    treated the same as "your navigation screen is covered".

    `aliases` lets a catalog phrase be recognised by the customer's own
    wording ("navigation screen" for "factory-installed navigation screen").
    """
    terms = [subject] + list(aliases or [])
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        sent = sentence.lower()
        if not any(term.lower() in sent for term in terms):
            continue
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


def _clauses(sentence: str) -> List[str]:
    """Split a sentence into clauses.

    Commas, conjunctions and contrastive conjunctions separate a coverage
    assertion from whatever the next clause says about the same subject, so
    that "the engine is covered by DriveWrap, but the alternator is not
    covered" is judged clause by clause instead of as one mixed statement.
    Splitting on "and" also separates coordinated claims about different
    plans ("CoreDrive covers X and CoreDrive Plus covers Y").
    """
    parts = re.split(r"[;:,]|\b(?:but|however|whereas|although|though|while|and)\b", sentence)
    return [part.strip() for part in parts if part.strip()]


def _plan_context(clause: str, allowed_plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Plans a clause talks about.

    A plan id or name in the clause names that plan. A shorter plan name that
    is only present because it is part of a longer one ("CoreDrive" inside
    "CoreDrive Plus") does not count.
    """
    lowered = clause.lower()
    spans: List[tuple] = []
    for plan in allowed_plans:
        for token in (str(plan.get("id", "")), str(plan.get("name", ""))):
            if not token:
                continue
            for match in re.finditer(rf"\b{re.escape(token.lower())}\b", lowered):
                spans.append((match.start(), match.end(), plan))
    if not spans:
        return []

    # Drop a span that sits inside a longer span (a shorter plan name inside
    # a longer one).
    kept: List[tuple] = []
    for span in spans:
        start, end, plan = span
        inside = any(
            other_start <= start and end <= other_end
            and (other_end - other_start) > (end - start)
            for other_start, other_end, _ in spans
        )
        if not inside:
            kept.append(span)

    named: List[Dict[str, Any]] = []
    for _, _, plan in kept:
        if plan not in named:
            named.append(plan)
    return named


def _component_coverage_violations(
    answer: str,
    fact_pack: Dict[str, Any],
    catalog: Catalog,
) -> List[str]:
    """Reject answers that claim coverage for a part the plan does not cover.

    The catalog is the authority here: a part that is explicitly excluded by
    the plan in question (DriveWrap and the powertrain) or that is not in the
    plan's covered list must never be described as covered.

    Sentence-scoped and negation-aware, so that "the engine is not covered"
    is not treated as a claim.
    """
    violations: List[str] = []
    allowed_plans = list(fact_pack.get("allowed_plans", []))
    if not allowed_plans:
        return violations

    # Coverage that comes from an option is governed by the "option purchased"
    # check instead: an option may legitimately be named as the thing that
    # covers a part, whether or not it has been bought.
    option_covered = set()
    option_excluded = set()
    for option in fact_pack.get("option_status", []):
        option_covered.update(option.get("covers", []))
        option_excluded.update(option.get("excludes", []))

    referent = fact_pack.get("referent_plan") or {}

    # The plan most recently named anywhere in the answer. A bare list such
    # as "Covers engine internal lubricated parts" continues the plan that
    # was named just before it ("- CoreDrive (P-BASE): ... Covers ...").
    last_plan: Optional[Dict[str, Any]] = None

    def context_for(clause: str) -> List[Dict[str, Any]]:
        named = _plan_context(clause, allowed_plans)
        if named:
            return named
        # No plan named in the clause: fall back to the plan named most
        # recently, then to the plan the customer is asking about, then to
        # the only allowed plan.
        if last_plan is not None:
            return [last_plan]
        if referent and referent.get("id") in {p.get("id") for p in allowed_plans}:
            return [referent]
        if len(allowed_plans) == 1:
            return [allowed_plans[0]]
        return []

    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        if not sentence.strip():
            continue
        # A coverage assertion can be introduced once and then apply to the
        # items of a list: "Covers engine internal lubricated parts,
        # transmission internal lubricated parts". The assertion therefore
        # carries over to the following clauses of the same sentence.
        asserts_coverage = False
        for clause in _clauses(sentence):
            named = _plan_context(clause, allowed_plans)
            if named:
                last_plan = named[0]
            sent = clause.lower()
            if any(marker in sent for marker in NEGATIVE_MARKERS):
                # A negation or a refusal is not a coverage assertion.
                continue
            if any(pos in sent for pos in POSITIVE_MARKERS):
                asserts_coverage = True
            if not asserts_coverage:
                continue

            spans = mentioned_component_spans(clause, catalog)
            components = []
            for _, _, component in spans:
                if component not in components:
                    components.append(component)
            if not components:
                continue

            context = context_for(clause)
            if not context:
                continue

            for component in components:
                if component in option_covered:
                    # Option coverage is checked against the purchase state.
                    continue
                if component in option_excluded:
                    violations.append(
                        f"Answer claims '{component}' is covered, but it is excluded "
                        f"by the optional coverage on this plan."
                    )
                    continue
                covered_by = [
                    plan
                    for plan in context
                    if component in (plan.get("covered_components") or [])
                ]
                if covered_by:
                    continue
                excluded_by = [
                    plan
                    for plan in context
                    if component in (plan.get("explicitly_excluded_components") or [])
                    or component in (plan.get("exclusions") or [])
                ]
                if excluded_by:
                    names = ", ".join(
                        str(plan.get("name", plan.get("id"))) for plan in excluded_by
                    )
                    violations.append(
                        f"Answer claims '{component}' is covered, but {names} "
                        f"explicitly excludes it."
                    )
                    continue
                # An exclusionary-style plan has no component list, so absence
                # proves nothing. For a plan with an explicit list, absence
                # means the part is not covered by it.
                explicit_plans = [
                    plan
                    for plan in context
                    if plan.get("coverage_style") != "broad_exclusions"
                ]
                if explicit_plans:
                    names = ", ".join(
                        str(plan.get("name", plan.get("id"))) for plan in explicit_plans
                    )
                    violations.append(
                        f"Answer claims '{component}' is covered, but it is not in "
                        f"the covered list of {names}."
                    )
    return violations


def _monetary_violations(
    answer: str,
    fact_pack: Dict[str, Any],
    catalog: Catalog,
) -> List[str]:
    """Validate each money amount against the plan it is attributed to.

    A fabricated amount is rejected everywhere. An amount that is valid for
    *some* allowed plan is still rejected when the clause that contains it
    attributes it to a different plan (for example "$139" for CoreDrive,
    whose price is $89). Benefit amounts (rental cap, ...) are plan-free
    and always acceptable.
    """
    violations: List[str] = []
    allowed_plans = list(fact_pack.get("allowed_plans", []))
    if not allowed_plans:
        return violations

    plan_amounts: Dict[str, set] = {}
    for plan in allowed_plans:
        amounts: set = set()
        for key in ("monthly_price", "deductible"):
            v = _normalize_money(plan.get(key))
            if v is not None:
                amounts.add(v)
        plan_amounts[str(plan.get("id"))] = amounts

    benefit_amounts: set = set()
    for value in (fact_pack.get("benefits") or {}).values():
        for key, amount in value.items():
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                benefit_amounts.add(float(amount))

    referent = fact_pack.get("referent_plan") or {}
    last_plan: Optional[Dict[str, Any]] = None

    def context_for(clause: str) -> List[Dict[str, Any]]:
        named = _plan_context(clause, allowed_plans)
        if named:
            return named
        if last_plan is not None:
            return [last_plan]
        if referent and referent.get("id") in {p.get("id") for p in allowed_plans}:
            return [referent]
        if len(allowed_plans) == 1:
            return [allowed_plans[0]]
        return []

    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        if not sentence.strip():
            continue
        for clause in _clauses(sentence):
            named = _plan_context(clause, allowed_plans)
            if named:
                last_plan = named[0]
            sent = clause.lower()
            if any(marker in sent for marker in NEGATIVE_MARKERS):
                # "does not cost $139" is a true disclaimer, not a misquote.
                continue
            context = context_for(clause)
            if not context:
                continue
            amounts = _money_values(clause)
            if not amounts:
                continue
            allowed: set = set()
            for plan in context:
                allowed |= plan_amounts.get(str(plan.get("id")), set())
            allowed |= benefit_amounts
            for amount in amounts:
                if amount not in allowed:
                    names = ", ".join(
                        str(p.get("name", p.get("id"))) for p in context
                    )
                    violations.append(
                        f"Amount ${amount:g} does not match {names}."
                    )
    return violations


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

    # 4b. money values must match the plan they are attributed to.
    violations.extend(_monetary_violations(answer, fact_pack, catalog))

    # 5. option coverage without purchase
    #
    # The part may be named with the customer's own words ("your navigation
    # screen"), so the match is done through the alias table rather than on
    # the catalog phrase alone.
    for option in fact_pack.get("option_status", []):
        if option["purchased"]:
            continue
        for covered in option["covers"]:
            aliases = [
                alias
                for alias, component in COMPONENT_ALIASES.items()
                if component == covered
            ]
            terms = [covered] + aliases
            if not any(
                re.search(rf"\b{re.escape(term.lower())}\b", lowered) for term in terms
            ):
                continue
            if _asserts_coverage(answer, covered, aliases):
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

    # 7. the answer must not claim coverage for a part the plan excludes
    violations.extend(_component_coverage_violations(answer, fact_pack, catalog))

    return GuardrailResult(ok=not violations, violations=violations, answer=answer)
