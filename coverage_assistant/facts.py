"""Intent detection and construction of the grounded fact pack.

The fact pack is the *only* information the language model is given about
coverage. It is computed in code from the catalog and the authorized state,
so every number the model might repeat is traceable to `data/plans.json`.

Intent detection is keyword-based and deliberately coarse. It exists to
choose a safe response *shape* and to feed the validator, not to replace
understanding. When intent is ambiguous the assistant asks a clarifying
question rather than guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .catalog import Catalog
from .state import NormalizedState, Referent

# Keyword groups per intent. More specific groups are listed first; ties are
# broken alphabetically so detection stays deterministic.
INTENT_KEYWORDS: Dict[str, List[str]] = {
    "universal_cover": [
        "everything",
        "literally everything",
        "all parts",
        "any part",
        "any repair",
        "whatever i ask",
        "whatever i ask about",
        "comprehensive",
        "bumper to bumper",
        "any damage",
        "anything",
    ],
    "price": ["price", "cost", "how much", "monthly", "premium", "fee", "charge", "pay per month"],
    "deductible": ["deductible"],
    "coverage": ["cover", "coverage", "covered", "include", "includes", "protect", "protection"],
    "component": ["engine", "transmission", "axle", "alternator", "starter", "radiator", "compressor",
                  "suspension", "control arm", "brake", "catalytic", "navigation", "camera", "screen"],
    "option": ["option", "add-on", "addon", "electronics", "exhaust", "purchase", "buy", "upgrade"],
    "benefit": ["rental", "car rental", "rental car", "trip interruption", "trip", "benefit", "per day", "per-day"],
    "eligibility": ["eligible", "eligibility", "qualify", "qualified", "available to me", "can i get",
                    "can i have", "offered", "offer"],
    "comparison": ["compare", "comparison", "difference", "differences", "vs", "versus", "better", "best",
                   "most coverage", "which plan", "which of these"],
    "claim": ["claim", "covered if", "will you pay", "reimburse", "approved", "denied", "pay out"],
    "exclusion": ["exclude", "exclusion", "not covered", "excluded", "isn't covered", "is not covered"],
}

# Phrases that constitute an unqualified universal coverage promise.
UNIVERSAL_GUARD = [
    "covers everything",
    "covers all",
    "covers anything",
    "covers every",
    "covers any",
    "everything is covered",
    "all repairs are covered",
    "any repair is covered",
    "whatever you ask",
    "no exclusions",
    "never excluded",
    "always covered",
    "guaranteed to cover",
    "fully covers",
    "complete coverage",
    "every part is covered",
    "all parts are covered",
    "every component is covered",
    "all components are covered",
]


@dataclass
class Intent:
    """Detected intent plus the signals the validator needs."""

    primary: str = "general"
    all: List[str] = field(default_factory=list)
    asked_universal: bool = False
    mentions_claim: bool = False
    mentions_availability: bool = False

    @property
    def is_universal_request(self) -> bool:
        return self.primary == "universal_cover" or self.asked_universal


def detect_intent(question: str) -> Intent:
    """Classify the question into one or more intents."""
    lowered = question.lower()
    scores: Dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in lowered)
        if hits:
            scores[intent] = hits

    result = Intent()
    if scores:
        ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        result.primary = ordered[0][0]
        result.all = [name for name, _ in ordered]

    result.asked_universal = "universal_cover" in result.all
    result.mentions_claim = "claim" in result.all
    result.mentions_availability = "eligibility" in result.all
    return result


# Markers that negate a claim appearing in the same sentence. "I cannot say
# this covers everything" is a refusal, not a promise, so the detector has
# to look at the sentence around the phrase rather than the whole document.
NEGATION_MARKERS = [
    "not",
    "no ",
    "never",
    "cannot",
    "can't",
    "cannot say",
    "do not",
    "don't",
    "doesn't",
    "isn't",
    "is not",
    "won't",
    "without",
    "unless",
    "rather than",
    "instead of",
    "unable",
    "deny",
    "denies",
    "refuse",
    "reject",
    "excluded",
    "exception",
]


def detect_universal_claim(text: str) -> bool:
    """True when a *response* makes an unqualified universal coverage promise.

    Sentence-scoped and negation-aware: a phrase such as "this does not
    cover everything" is a correct disclaimer and must not be flagged,
    while "this covers everything" must be.
    """
    import re

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sent = sentence.lower()
        for phrase in UNIVERSAL_GUARD:
            index = sent.find(phrase)
            if index == -1:
                continue
            # Look at the text preceding the phrase within the sentence.
            prefix = sent[:index]
            if any(marker in prefix for marker in NEGATION_MARKERS):
                continue
            return True
    return False



# Short forms a customer would actually use, mapped to the catalog wording.
# Matching on the catalog phrase alone is too strict: a customer says
# "engine", the catalog says "engine internal lubricated parts".
COMPONENT_ALIASES: Dict[str, str] = {
    "engine": "engine internal lubricated parts",
    "transmission": "transmission internal lubricated parts",
    "gearbox": "transmission internal lubricated parts",
    "axle": "drive axle internal parts",
    "differential": "drive axle internal parts",
    "alternator": "alternator",
    "starter": "starter motor",
    "starter motor": "starter motor",
    "radiator": "factory-installed radiator",
    "a/c": "factory air-conditioning compressor",
    "air conditioning": "factory air-conditioning compressor",
    "air-conditioning": "factory air-conditioning compressor",
    "compressor": "factory air-conditioning compressor",
    "suspension": "front suspension control arms",
    "control arm": "front suspension control arms",
    "brake": "brake pads and brake rotors",
    "brake pads": "brake pads and brake rotors",
    "brake rotors": "brake pads and brake rotors",
    "catalytic converter": "factory-installed catalytic converter",
    "catalytic": "factory-installed catalytic converter",
    "navigation": "factory-installed navigation screen",
    "navigation screen": "factory-installed navigation screen",
    "screen": "factory-installed navigation screen",
    "camera": "factory-installed rear parking camera",
    "parking camera": "factory-installed rear parking camera",
}


def component_vocabulary(catalog: Catalog) -> List[str]:
    """Every catalog component phrase the assistant is allowed to recognise.

    Covers covered components, explicitly excluded components, named
    exclusions and option-level items, so that a customer's word for a part
    always maps onto catalog wording.
    """
    known: List[str] = []

    def add(item: str) -> None:
        if item not in known:
            known.append(item)

    for plan_id in catalog.plan_ids():
        for component in catalog.components(plan_id)["items"]:
            add(component)
        for component in catalog.explicitly_excluded_components(plan_id):
            add(component)
    # Named exclusions are part of the vocabulary as well: a customer asks
    # about "brake pads" precisely because they want to know if they are
    # excluded.
    for plan_id in catalog.plan_ids():
        for exclusion in catalog.exclusions(plan_id):
            add(exclusion)
    # Option-level items (navigation screen, catalytic converter, ...) are
    # part of the vocabulary too, even though they sit under options.
    for option in catalog.options.values():
        for covered in option.get("covers", []):
            add(covered)
        for excluded in option.get("excludes", []):
            add(excluded)
    return known


def _contains_term(lowered: str, term: str) -> bool:
    """True when `term` occurs in `lowered` as a whole word or phrase.

    Plain substring matching is wrong for this vocabulary: the alias
    "engine" would otherwise match "engineer", and "screen" would match
    "screening". Requiring a non-word character on both sides keeps
    "engine" from matching "engineer" while still matching
    "the engine is covered" and "engine,".
    """
    if not term:
        return False
    pattern = rf"(?<!\w){re.escape(term.lower())}(?!\w)"
    return re.search(pattern, lowered) is not None


def mentioned_component_spans(
    text: str, catalog: Catalog
) -> List[tuple]:
    """Positions of catalog component mentions in a text.

    Returns a list of ``(start, end, component)`` tuples. Longer phrases win
    over shorter ones, and overlapping mentions are resolved so that a
    single span of text maps to a single component.
    """
    lowered = (text or "").lower()
    known = component_vocabulary(catalog)
    candidates: List[tuple] = []

    for component in known:
        for match in re.finditer(
            rf"(?<!\w){re.escape(component.lower())}(?!\w)", lowered
        ):
            candidates.append((match.start(), match.end(), component))

    for alias, component in COMPONENT_ALIASES.items():
        if component not in known:
            continue
        for match in re.finditer(rf"(?<!\w){re.escape(alias.lower())}(?!\w)", lowered):
            candidates.append((match.start(), match.end(), component))

    # Longest match wins; an equal-length match at the same position is
    # resolved by keeping the first one seen.
    candidates.sort(key=lambda span: (-(span[1] - span[0]), span[0]))
    selected: List[tuple] = []
    for span in candidates:
        start, end, _ = span
        if any(start < other_end and other_start < end for other_start, other_end, _ in selected):
            continue
        selected.append(span)
    selected.sort(key=lambda span: span[0])
    return selected


def mentioned_components(text: str, catalog: Catalog) -> List[str]:
    """Catalog component phrases mentioned in a piece of text.

    Matches the full catalog phrase first, then short aliases, so that
    "does it cover my engine" resolves to the catalog's
    "engine internal lubricated parts". Used both for the customer's
    question and for the model's answer, so that the validator can tell
    which part an answer is talking about.

    Matching is word-boundary aware. A bare substring test would let
    "engine" match "engineer" and "screen" match "screening", which
    would make the validator judge a claim about the wrong part.
    """
    seen: List[str] = []
    for _, _, component in mentioned_component_spans(text, catalog):
        if component not in seen:
            seen.append(component)
    return seen


def _component_mentions(question: str, catalog: Catalog) -> List[str]:
    """Catalog component phrases mentioned in the question."""
    return mentioned_components(question, catalog)


def build_fact_pack(
    question: str,
    state: NormalizedState,
    referent: Referent,
    catalog: Catalog,
    intent: Intent,
) -> Dict[str, Any]:
    """Assemble the grounded, authorized fact pack for one turn.

    Only plans in ``state.allowed_ids`` get a full fact entry. Plans that
    exist in the catalog but are not authorized appear only as an
    ``unavailable`` note with *no* details, so the model cannot leak the
    price or components of a plan the customer may not see.
    """
    allowed = catalog.ordered_ids(state.allowed_ids)
    plan_facts = [catalog.plan_facts(pid) for pid in allowed]

    selected_id = state.selected_id if state.is_allowed(state.selected_id or "") else None

    purchased_options = list(state.selected_options)
    offered_options: List[str] = []
    for pid in allowed:
        for option_id in catalog.options_available(pid):
            if option_id not in offered_options:
                offered_options.append(option_id)

    option_facts = [
        catalog.option_facts(oid)
        for oid in sorted(set(purchased_options) | set(offered_options))
    ]

    benefits = {name: dict(value) for name, value in catalog.benefits.items()}

    referent_facts = None
    if referent.plan_id and catalog.has(referent.plan_id):
        referent_facts = catalog.plan_facts(referent.plan_id)

    components_mentioned = _component_mentions(question, catalog)

    # Which option covers a mentioned component, and is it purchased?
    option_status: List[Dict[str, Any]] = []
    for option in option_facts:
        covers_mentioned = [c for c in option["covers"] if c in components_mentioned]
        option_status.append(
            {
                "id": option["id"],
                "covers": option["covers"],
                "excludes": option["excludes"],
                "purchased": option["id"] in purchased_options,
                "covers_mentioned_components": covers_mentioned,
            }
        )

    # Only plans the customer actually named appear here. Plans nobody
    # mentioned must not be surfaced at all, otherwise the fact pack itself
    # becomes a catalogue of products the customer may not see.
    unavailable: List[Dict[str, Any]] = []
    for plan_id in referent.mentioned_ids:
        if plan_id in allowed:
            continue
        if plan_id in state.eligible_ids:
            reason = "not currently visible for you"
        else:
            reason = "not currently available to you"
        unavailable.append({"id": plan_id, "availability": reason})

    return {
        "question": question,
        "intent": intent.primary,
        "intents": intent.all,
        "asked_universal": intent.asked_universal,
        "mentions_claim": intent.mentions_claim,
        "allowed_plan_ids": allowed,
        "allowed_plans": plan_facts,
        "selected_plan_id": selected_id,
        "referent_plan_id": referent.plan_id,
        "referent_source": referent.source,
        "referent_plan": referent_facts,
        "mentioned_components": components_mentioned,
        "purchased_options": purchased_options,
        "offered_options": offered_options,
        "option_status": option_status,
        "benefits": benefits,
        "claims_conditions": list(catalog.claims_conditions),
        "unavailable_plans": unavailable,
        "explicitly_mentioned_but_unavailable": [
            m for m in referent.mentioned_ids if m not in allowed
        ],
        # Ids the customer named that the assistant may not describe.
        "blocked_plan_ids": [m for m in referent.mentioned_ids if m not in allowed],
        "catalog_notes": catalog.notes,
    }
