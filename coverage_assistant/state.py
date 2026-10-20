"""Application state: normalization, authorization and referent resolution.

Three responsibilities, kept separate from generation on purpose:

1. **Normalize** whatever the caller hands us. State arrives from a UI, an
   API, or a test, and may be malformed (missing keys, unknown plan ids,
   non-list values, ids from a previous session). We never crash on it and
   never silently widen it.
2. **Authorize.** The set of plans the assistant may talk about is
   ``eligible_ids ∩ visible_ids``. A plan outside that intersection is
   off-limits, even if the customer names it explicitly. This mirrors the
   starter bug where ``visible_ids`` was read from nowhere.
3. **Resolve the referent.** "it", "that plan", "the second one" must point
   at the plan the customer is actually talking about *now*, which may have
   changed since the previous turn (a selection change is an event, not a
   suggestion).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .catalog import Catalog

# Words that refer back to the current subject.
PRONOUNS = {
    "it",
    "its",
    "that",
    "this",
    "the same",
    "that one",
    "this one",
    "the other",
    "they",
    "them",
}


@dataclass
class NormalizedState:
    """A validated, authorization-ready view of application state."""

    eligible_ids: List[str] = field(default_factory=list)
    visible_ids: List[str] = field(default_factory=list)
    selected_id: Optional[str] = None
    selected_options: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def allowed_ids(self) -> List[str]:
        """Plans the assistant is allowed to discuss or recommend.

        Intersection, not union: a plan must be *both* eligible and visible.
        """
        visible = set(self.visible_ids)
        return [pid for pid in self.eligible_ids if pid in visible]

    @property
    def visible_but_ineligible(self) -> List[str]:
        return [pid for pid in self.visible_ids if pid not in set(self.eligible_ids)]

    @property
    def eligible_but_hidden(self) -> List[str]:
        return [pid for pid in self.eligible_ids if pid not in set(self.visible_ids)]

    def is_allowed(self, plan_id: str) -> bool:
        return plan_id in self.allowed_ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligible_ids": list(self.eligible_ids),
            "visible_ids": list(self.visible_ids),
            "selected_id": self.selected_id,
            "selected_options": list(self.selected_options),
        }


def normalize_state(state: Any, catalog: Catalog) -> NormalizedState:
    """Validate and normalize a raw state payload.

    Rules:
    * Unknown plan ids are dropped and reported in ``warnings`` (never
      silently surfaced to the customer as a real plan).
    * A selected id that is not allowed is kept only as a *hint* for
      pronoun resolution when the customer names that plan directly;
      otherwise it is cleared.
    * ``selected_options`` are only honoured when the option id exists in
      the catalog.
    """
    warnings: List[str] = []
    if not isinstance(state, dict):
        warnings.append("State was not a mapping; treated as empty state.")
        state = {}

    def _id_list(key: str) -> List[str]:
        raw = state.get(key)
        if raw is None:
            warnings.append(f"'{key}' missing from state; treated as empty.")
            return []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            warnings.append(f"'{key}' was not a list; ignored.")
            return []
        out: List[str] = []
        for item in raw:
            if not isinstance(item, str):
                warnings.append(f"Ignored non-string entry in '{key}'.")
                continue
            if not catalog.has(item):
                warnings.append(f"Ignored unknown plan id '{item}' in '{key}'.")
                continue
            if item not in out:
                out.append(item)
        return out

    eligible = _id_list("eligible_ids")
    visible = _id_list("visible_ids")

    selected_raw = state.get("selected_id")
    selected: Optional[str] = None
    if isinstance(selected_raw, str) and selected_raw:
        if catalog.has(selected_raw):
            selected = selected_raw
        else:
            warnings.append(f"Selected plan '{selected_raw}' is not in the catalog; ignored.")

    options_raw = state.get("selected_options")
    if options_raw is None:
        options_raw = []
    if isinstance(options_raw, str):
        options_raw = [options_raw]
    options: List[str] = []
    if isinstance(options_raw, (list, tuple, set)):
        for item in options_raw:
            if not isinstance(item, str):
                continue
            if catalog.option(item) is None:
                warnings.append(f"Unknown option '{item}' ignored.")
                continue
            if item not in options:
                options.append(item)
    else:
        warnings.append("'selected_options' was not a list; ignored.")

    return NormalizedState(
        eligible_ids=eligible,
        visible_ids=visible,
        selected_id=selected,
        selected_options=options,
        warnings=warnings,
    )

# ----------------------------------------------------------------------
# referent resolution
# ----------------------------------------------------------------------
@dataclass
class Referent:
    """The plan the customer's question is about."""

    plan_id: Optional[str]
    source: str  # "explicit" | "selected" | "recent" | "only_allowed" | "none"
    mentioned_ids: List[str] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.plan_id is not None


def _mentions(text: str, plan_id: str, catalog: Catalog) -> bool:
    """True when the customer names a plan by id or by name.

    Longer names are matched first so that "CoreDrive Plus" is not read as
    a mention of "CoreDrive" as well. See `_plan_mention_order`.
    """
    lowered = text.lower()
    if plan_id.lower() in lowered:
        return True
    name = catalog.plan_name(plan_id)
    if not name:
        return False
    if name.lower() in lowered:
        # Guard against a shorter plan name being a substring of a longer
        # one ("CoreDrive" inside "CoreDrive Plus").
        for other_id in catalog.plan_ids():
            if other_id == plan_id:
                continue
            other = catalog.plan_name(other_id)
            if other and other.lower() != name.lower() and name.lower() in other.lower():
                if other.lower() in lowered:
                    return False
        return True
    # Tolerate the display name without spaces ("CoreDrivePlus").
    if name.replace(" ", "").lower() in lowered.replace(" ", ""):
        return True
    return False


def resolve_referent(
    question: str,
    state: NormalizedState,
    catalog: Catalog,
    recent_plan_ids: Optional[List[str]] = None,
) -> Referent:
    """Work out which plan the customer means.

    Precedence:
      1. Plans named in the question (explicit beats everything).
      2. The current selection, if it is allowed.
      3. The most recently discussed allowed plan, if the question is
         anaphoric ("what about its deductible?").
      4. The single allowed plan, if there is exactly one.
    """
    allowed = state.allowed_ids
    recent = list(recent_plan_ids or [])

    # Longest name first, so the most specific plan wins a mention.
    order = sorted(
        catalog.plan_ids(),
        key=lambda pid: (-len(catalog.plan_name(pid)), pid),
    )
    mentioned = [pid for pid in order if _mentions(question, pid, catalog)]
    allowed_mentions = [pid for pid in mentioned if pid in allowed]

    if allowed_mentions:
        return Referent(plan_id=allowed_mentions[0], source="explicit", mentioned_ids=mentioned)

    if state.selected_id and state.is_allowed(state.selected_id):
        return Referent(plan_id=state.selected_id, source="selected", mentioned_ids=mentioned)

    if _is_anaphoric(question):
        for pid in recent:
            if pid in allowed:
                return Referent(plan_id=pid, source="recent", mentioned_ids=mentioned)
        if len(allowed) == 1:
            return Referent(plan_id=allowed[0], source="only_allowed", mentioned_ids=mentioned)
        return Referent(plan_id=None, source="none", mentioned_ids=mentioned)

    if len(allowed) == 1:
        return Referent(plan_id=allowed[0], source="only_allowed", mentioned_ids=mentioned)

    return Referent(plan_id=None, source="none", mentioned_ids=mentioned)


def _is_anaphoric(question: str) -> bool:
    lowered = question.lower()
    return any(pronoun in lowered for pronoun in PRONOUNS)


def match_option_id(text: str, catalog: Catalog) -> Optional[str]:
    """Map free text to a catalog option id, if unambiguous.

    Handles both the raw id ("electronics_plus") and friendly variants
    ("electronics plus", "navigation screen" -> electronics_plus).
    """
    lowered = text.lower()
    for option_id in catalog.options:
        if option_id.lower() in lowered:
            return option_id
        if option_id.replace("_", " ") in lowered:
            return option_id
    for option_id, option in catalog.options.items():
        for covered in option.get("covers", []):
            if covered.lower() in lowered:
                return option_id
            # Match on the distinctive tail of the phrase, so a customer
            # saying "navigation screen" matches "factory-installed
            # navigation screen".
            tail = covered.lower().split(" ", 1)[-1]
            if len(tail) > 8 and tail in lowered:
                return option_id
    return None
