"""Deterministic answer rendering from the fact pack (no language model).

This module is the *safe* path: it produces an answer directly from
catalog data, so it cannot hallucinate a price, a component, or a coverage
promise. It is used by the offline adapter, and it is also the fallback the
assistant drops to when a live model's output fails validation.

Every rendered answer starts with the ``OFFLINE_DETERMINISTIC`` label so a
reviewer can never mistake it for model output.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

OFFLINE_LABEL = "OFFLINE_DETERMINISTIC - NOT AN LLM"


def _plan_by_id(fact_pack: Dict[str, Any], plan_id: str) -> Optional[Dict[str, Any]]:
    for plan in fact_pack.get("allowed_plans", []):
        if plan.get("id") == plan_id:
            return plan
    return None


def _money(value: Any) -> str:
    if value is None:
        return "not stated"
    if float(value) == int(float(value)):
        return f"${int(float(value))}"
    return f"${float(value):.2f}"


def _coverage_sentence(plan: Dict[str, Any]) -> str:
    """Describe what a plan covers, from catalog facts only."""
    if plan.get("coverage_style") == "broad_exclusions":
        wording = plan.get("coverage_wording") or "covered unless explicitly excluded"
        exclusions = plan.get("exclusions", [])
        return (
            f"{plan['name']} is written as \"{wording}\". "
            f"Items listed as exclusions are not covered: "
            f"{', '.join(exclusions) if exclusions else 'none listed in the catalog'}."
        )
    covered = plan.get("covered_components", [])
    excluded = plan.get("explicitly_excluded_components", [])
    parts = [
        f"{plan['name']} covers: {', '.join(covered) if covered else 'no components listed'}."
    ]
    if excluded:
        parts.append(f"It explicitly does not cover: {', '.join(excluded)}.")
    return " ".join(parts)


def _options_sentence(fact_pack: Dict[str, Any]) -> str:
    purchased = list(fact_pack.get("purchased_options", []))
    offered = list(fact_pack.get("offered_options", []))
    if not offered:
        return ""
    offered_text = ", ".join(offered)
    if purchased:
        return (
            f"Optional coverage: you have purchased {', '.join(purchased)}. "
            f"These are the optional items on your plan: {offered_text}."
        )
    return (
        f"Optional coverage: you have not purchased any optional coverage. "
        f"The optional items available on your plan are {offered_text} - "
        f"they are offered, not in force, until purchased."
    )


def _unavailable_sentence(fact_pack: Dict[str, Any]) -> str:
    mentioned = list(fact_pack.get("explicitly_mentioned_but_unavailable", []))
    entries = {
        item["id"]: item["availability"] for item in fact_pack.get("unavailable_plans", [])
    }
    if not mentioned:
        return ""
    parts = []
    for plan_id in mentioned:
        parts.append(f"{plan_id} is {entries.get(plan_id, 'not currently available to you')}.")
    return " ".join(parts)


def _benefit_sentence(fact_pack: Dict[str, Any], benefit_id: str) -> str:
    benefit = fact_pack.get("benefits", {}).get(benefit_id)
    if not benefit:
        return ""
    if benefit_id == "rental":
        cap = _money(benefit.get("daily_cap_usd"))
        days = benefit.get("max_days")
        requires = benefit.get("requires", [])
        not_cover = benefit.get("does_not_cover", [])
        text = (
            f"Rental reimbursement is not automatic. If it applies, it is up to "
            f"{cap} per day for a maximum of {days} days, and only when the "
            f"conditions are met: {'; '.join(requires)}."
        )
        if not_cover:
            text += f" It does not cover {'; '.join(not_cover)}."
        return text
    if benefit_id == "trip_interruption":
        cap = _money(benefit.get("daily_cap_usd"))
        days = benefit.get("max_days")
        distance = benefit.get("min_distance_from_home_miles_exclusive")
        requires = benefit.get("requires", [])
        return (
            f"Trip interruption, when it applies, pays up to {cap} per day for up to "
            f"{days} days, and only for a trip more than {distance} miles from home "
            f"where the requirements are met: {'; '.join(requires)}."
        )
    return ""


def _option_note(fact_pack: Dict[str, Any], component: str) -> str:
    """Explain that a component is only covered by an option, and its status."""
    for option in fact_pack.get("option_status", []):
        if component not in option.get("covers", []):
            continue
        if option.get("purchased"):
            return (
                f"{component} is covered by your {option['id']} option, which you have purchased."
            )
        return (
            f"{component} would be covered by the {option['id']} option. That option is "
            f"offered on your plan but has not been purchased, so {component} is not "
            f"currently covered."
        )
    return ""


def render_answer(fact_pack: Dict[str, Any]) -> str:
    """Compose a safe answer from the fact pack."""
    intent = fact_pack.get("intent", "general")
    question = fact_pack.get("question", "")
    referent = fact_pack.get("referent_plan")
    allowed = fact_pack.get("allowed_plans", [])

    blocks: List[str] = []

    if not allowed:
        blocks.append(
            "There are no plans currently available to you in this session, "
            "so I cannot describe coverage right now."
        )
        return f"{OFFLINE_LABEL}\n\n" + " ".join(blocks)

    # 1. Unavailable plan named by the customer.
    unavailable = _unavailable_sentence(fact_pack)
    if unavailable:
        blocks.append(unavailable)

    # 2. Universal coverage request.
    if fact_pack.get("asked_universal"):
        excluded_bits: List[str] = []
        for plan in allowed:
            for exclusion in plan.get("exclusions", []):
                excluded_bits.append(exclusion)
        unique_excluded: List[str] = []
        for item in excluded_bits:
            if item not in unique_excluded:
                unique_excluded.append(item)
        blocks.append(
            "No. I am not able to describe any plan here as covering everything. "
            "Every plan in the catalog carries exclusions, so there is no blanket "
            "promise to be made. "
            + (
                f"Exclusions that apply to the plans you can see include: "
                f"{', '.join(unique_excluded)}."
                if unique_excluded
                else "The catalog still lists exclusions that apply."
            )
        )
        if referent:
            blocks.append(_coverage_sentence(referent))

    # 3. Comparison across the allowed set.
    elif intent == "comparison" and len(allowed) > 1:
        lines = []
        for plan in allowed:
            lines.append(
                f"- {plan['name']} ({plan['id']}): {_money(plan.get('monthly_price'))}/month, "
                f"deductible {_money(plan.get('deductible'))}. "
                + (
                    f"Coverage is written as \"{plan.get('coverage_wording')}\"."
                    if plan.get("coverage_style") == "broad_exclusions"
                    else f"Covers {', '.join(plan.get('covered_components', []))}."
                )
            )
        blocks.append(
            "Here is how the plans you can see compare: " + " ".join(lines)
        )

    # 4. Price.
    elif intent == "price":
        if referent:
            blocks.append(
                f"{referent['name']} is {_money(referent.get('monthly_price'))} per month, "
                f"with a {_money(referent.get('deductible'))} deductible."
            )
        else:
            blocks.append(
                "The plans you can see are priced as: "
                + ", ".join(f"{p['name']} {_money(p.get('monthly_price'))}/month" for p in allowed)
                + "."
            )

    # 5. Deductible.
    elif intent == "deductible":
        if referent:
            blocks.append(
                f"The deductible for {referent['name']} ({referent['id']}) is "
                f"{_money(referent.get('deductible'))}."
            )
        else:
            blocks.append(
                "Deductibles for the plans you can see: "
                + ", ".join(f"{p['name']} {_money(p.get('deductible'))}" for p in allowed)
                + "."
            )

    # 6. Option status.
    elif intent == "option":
        options_text = _options_sentence(fact_pack)
        if options_text:
            blocks.append(options_text)
        mentioned = fact_pack.get("mentioned_components", [])
        for option in fact_pack.get("option_status", []):
            hits = option.get("covers_mentioned_components", [])
            if not hits:
                continue
            if option.get("purchased"):
                blocks.append(
                    f"Your {option['id']} option covers {', '.join(hits)}."
                )
            else:
                blocks.append(
                    f"{', '.join(hits)} would be covered by the {option['id']} option, "
                    f"which is offered on your plan but has not been purchased, "
                    f"so it is not in force."
                )
        if not mentioned:
            blocks.append(
                "Tell me which part you are asking about and I will check it against the catalog."
            )

    # 7. Benefits.
    elif intent == "benefit":
        rental = _benefit_sentence(fact_pack, "rental")
        trip = _benefit_sentence(fact_pack, "trip_interruption")
        if rental:
            blocks.append(rental)
        if trip:
            blocks.append(trip)
        if not rental and not trip:
            blocks.append(
                "I do not have a benefit that matches that question in the catalog."
            )

    # 8. Claims decision.
    elif intent == "claim":
        blocks.append(
            "I cannot approve or decline a claim. The final claims decision is made "
            "by the administrator after the repair is authorised."
        )
        if referent:
            blocks.append(_coverage_sentence(referent))

    # 9. Availability / eligibility.
    elif intent == "eligibility":
        blocks.append(
            "Your eligibility is set by the application, not by me. The plans you can "
            "see right now are: "
            + ", ".join(f"{p['name']} ({p['id']})" for p in allowed)
            + "."
        )

    # 10. Component coverage question.
    elif intent == "component":
        mentioned = fact_pack.get("mentioned_components", [])
        if referent:
            if referent.get("coverage_style") == "broad_exclusions":
                blocks.append(_coverage_sentence(referent))
            else:
                covered = referent.get("covered_components", [])
                excluded = referent.get("explicitly_excluded_components", [])
                for component in mentioned:
                    if component in covered:
                        blocks.append(
                            f"{component} is covered by {referent['name']}."
                        )
                    elif component in excluded:
                        blocks.append(
                            f"{component} is not covered by {referent['name']}; "
                            f"it is explicitly excluded."
                        )
                    else:
                        option_note = _option_note(fact_pack, component)
                        if option_note:
                            blocks.append(option_note)
                        else:
                            blocks.append(
                                f"{component} is not listed as covered by {referent['name']}. "
                                f"{referent['name']} covers: {', '.join(covered) if covered else 'no components listed'}."
                            )
            requires = referent.get("requires")
            if requires:
                blocks.append(f"Note: {referent['name']} requires {requires}.")
        else:
            blocks.append(
                "I could not tell which plan you mean from the plans you can see: "
                + ", ".join(f"{p['name']} ({p['id']})" for p in allowed)
                + "."
            )

    # 11. Exclusion question.
    elif intent == "exclusion":
        if referent:
            blocks.append(
                f"{referent['name']} excludes: "
                f"{', '.join(referent.get('exclusions', [])) or 'nothing listed in the catalog'}."
            )
        else:
            blocks.append(
                "Exclusions across the plans you can see: "
                + "; ".join(
                    f"{p['name']}: {', '.join(p.get('exclusions', []))}" for p in allowed
                )
                + "."
            )

    # 12. Default: describe the plan in question.
    else:
        if referent:
            blocks.append(_coverage_sentence(referent))
            blocks.append(
                f"{referent['name']} ({referent['id']}) is "
                f"{_money(referent.get('monthly_price'))} per month with a "
                f"{_money(referent.get('deductible'))} deductible."
            )
            requires = referent.get("requires")
            if requires:
                blocks.append(f"Note: {referent['name']} requires {requires}.")
        else:
            blocks.append(
                "I could not tell which plan you mean from the plans you can see: "
                + ", ".join(f"{p['name']} ({p['id']})" for p in allowed)
                + "."
            )

    options_text = _options_sentence(fact_pack)
    if options_text and intent not in ("option",):
        blocks.append(options_text)

    conditions = fact_pack.get("claims_conditions", [])
    if conditions and intent in ("claim", "component", "universal_cover", "coverage"):
        blocks.append("Please note: " + "; ".join(conditions) + ".")

    body = " ".join(b for b in blocks if b)
    return f"{OFFLINE_LABEL}\n\n{body}"
