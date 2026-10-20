"""Catalog loading and plan resolution.

`data/plans.json` is the single source of truth for contract facts
(components, prices, deductibles, options, benefit conditions).

Hard rule enforced here: **eligibility is never inferred from the catalog.**
The catalog knows what a plan *is*; application state decides what a customer
may see or be offered. `data/plans.json` says so explicitly in its `notes`
field, and this module keeps that separation clean.

Special case handled deliberately: `P-WRAP` (DriveWrap) has no `inherits`
key, so it inherits *nothing*. Its `explicitly_excludes` list names the
powertrain internals, which means "wrap" must never be treated as
"CoreDrive Plus minus the engine".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "plans.json"


def _money_display(value: Any) -> Optional[str]:
    """Format a catalog amount the way the catalog states it."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == int(number):
        return f"${int(number)}"
    return f"${number:.2f}"


class CatalogError(RuntimeError):
    """Raised when the catalog file is missing or structurally unusable."""


class Catalog:
    """Read-only, resolved view over the coverage catalog."""

    def __init__(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict) or "plans" not in data:
            raise CatalogError("Catalog file must be an object containing a 'plans' list.")
        self.disclaimer: str = data.get("disclaimer", "")
        self.notes: str = data.get("notes", "")
        self.plans: Dict[str, Dict[str, Any]] = {}
        for plan in data["plans"]:
            if "id" not in plan:
                raise CatalogError("Every plan needs an 'id'.")
            self.plans[plan["id"]] = plan
        self.options: Dict[str, Any] = data.get("options", {})
        self.benefits: Dict[str, Any] = data.get("benefits", {})
        self.claims_conditions: List[str] = list(data.get("claims_conditions", []))
        self.comparison_order: List[str] = list(data.get("comparison_order", []))

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Catalog":
        target = Path(path) if path is not None else DEFAULT_DATA_PATH
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise CatalogError(f"Could not read catalog at {target}: {exc}") from exc
        try:
            return cls(json.loads(text))
        except json.JSONDecodeError as exc:
            raise CatalogError(f"Catalog at {target} is not valid JSON: {exc}") from exc

    # ------------------------------------------------------------------
    # basic lookups
    # ------------------------------------------------------------------
    def has(self, plan_id: str) -> bool:
        return plan_id in self.plans

    def plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Raw plan record, or None when the id is unknown."""
        return self.plans.get(plan_id)

    def plan_ids(self) -> List[str]:
        return list(self.plans)

    def plan_name(self, plan_id: str) -> str:
        plan = self.plans.get(plan_id)
        return plan.get("name", plan_id) if plan else plan_id

    def options_available(self, plan_id: str) -> List[str]:
        plan = self.plans.get(plan_id) or {}
        return list(plan.get("options_available", []))

    def option(self, option_id: str) -> Optional[Dict[str, Any]]:
        return self.options.get(option_id)

    def benefit(self, benefit_id: str) -> Optional[Dict[str, Any]]:
        return self.benefits.get(benefit_id)

    # ------------------------------------------------------------------
    # inheritance
    # ------------------------------------------------------------------
    def inherited_from(self, plan_id: str) -> List[str]:
        """Transitive parents of a plan, resolved breadth-first.

        Cycle-safe: a plan that (incorrectly) formed a cycle is simply not
        followed a second time.
        """
        plan = self.plans.get(plan_id) or {}
        ordered: List[str] = []
        queue: List[str] = list(plan.get("inherits", []))
        while queue:
            parent_id = queue.pop(0)
            if parent_id in ordered or parent_id not in self.plans:
                continue
            ordered.append(parent_id)
            queue.extend(self.plans[parent_id].get("inherits", []))
        return ordered

    def inherits_from(self, plan_id: str, ancestor_id: str) -> bool:
        return ancestor_id in self.inherited_from(plan_id)


    # ------------------------------------------------------------------
    # resolved coverage
    # ------------------------------------------------------------------
    def components(self, plan_id: str) -> Dict[str, Any]:
        """Resolved component coverage for a plan.

        Returns a dict with:
          broad     - True when the plan uses "covered unless excluded" wording
                      (exclusionary style) instead of an explicit component list.
          items     - explicit covered components, parents included.
          own       - components declared directly on the plan.
          inherited - components contributed by inherited plans.
        """
        plan = self.plans.get(plan_id)
        if plan is None:
            return {"broad": False, "items": [], "own": [], "inherited": []}

        own_raw = plan.get("components", [])
        if isinstance(own_raw, str):
            # Exclusionary-style plan ("covered unless explicitly excluded").
            return {
                "broad": True,
                "items": [],
                "own": [],
                "inherited": [],
                "wording": own_raw,
            }

        own = list(own_raw)
        inherited: List[str] = []
        for parent_id in self.inherited_from(plan_id):
            parent = self.plans.get(parent_id) or {}
            parent_components = parent.get("components", [])
            if isinstance(parent_components, list):
                inherited.extend(parent_components)
        items: List[str] = []
        for item in own + inherited:
            if item not in items:
                items.append(item)
        return {
            "broad": False,
            "items": items,
            "own": own,
            "inherited": inherited,
        }

    def exclusions(self, plan_id: str) -> List[str]:
        """Resolved exclusions: own + inherited exclusions + explicitly-excluded
        items, denormalised into one list.

        `explicitly_excludes` is how P-WRAP states that it does *not* cover
        powertrain internals; keeping it in the same bucket lets the
        validator reason about "is this component covered?" uniformly.
        """
        plan = self.plans.get(plan_id)
        if plan is None:
            return []
        resolved: List[str] = []
        for source in [plan] + [self.plans[p] for p in self.inherited_from(plan_id)]:
            for exclusion in source.get("exclusions", []):
                if exclusion not in resolved:
                    resolved.append(exclusion)
            for exclusion in source.get("explicitly_excludes", []):
                if exclusion not in resolved:
                    resolved.append(exclusion)
        return resolved

    def explicitly_excluded_components(self, plan_id: str) -> List[str]:
        plan = self.plans.get(plan_id) or {}
        excluded = list(plan.get("explicitly_excludes", []))
        for parent_id in self.inherited_from(plan_id):
            excluded.extend(self.plans[parent_id].get("explicitly_excludes", []))
        return excluded

    def requires(self, plan_id: str) -> Optional[str]:
        plan = self.plans.get(plan_id) or {}
        return plan.get("requires")

    def monthly_price(self, plan_id: str) -> Optional[float]:
        plan = self.plans.get(plan_id) or {}
        return plan.get("monthly_price")

    def deductible(self, plan_id: str) -> Optional[float]:
        plan = self.plans.get(plan_id) or {}
        return plan.get("deductible")

    def tier(self, plan_id: str) -> str:
        plan = self.plans.get(plan_id) or {}
        return plan.get("tier", "")

    # ------------------------------------------------------------------
    # ordering
    # ------------------------------------------------------------------
    def ordered_ids(self, plan_ids: List[str]) -> List[str]:
        """Sort ids by the catalog's `comparison_order`, unknown ids last.

        Used so comparisons are deterministic and match the catalog's own
        intended presentation order rather than whatever order the caller
        happened to pass in.
        """
        order = {plan_id: index for index, plan_id in enumerate(self.comparison_order)}
        return sorted(plan_ids, key=lambda pid: (order.get(pid, len(order)), pid))

    # ------------------------------------------------------------------
    # fact pack
    # ------------------------------------------------------------------
    def plan_facts(self, plan_id: str) -> Dict[str, Any]:
        """Machine-checkable facts about one plan, for the LLM and validator.

        Numbers are included raw (for the validator) and also as display
        strings (so the model can quote them exactly, with the currency
        symbol, rather than reformatting them).
        """
        plan = self.plans.get(plan_id)
        if plan is None:
            return {}
        components = self.components(plan_id)
        price = self.monthly_price(plan_id)
        deductible = self.deductible(plan_id)
        return {
            "id": plan_id,
            "name": self.plan_name(plan_id),
            "tier": self.tier(plan_id),
            "monthly_price": price,
            "monthly_price_display": _money_display(price),
            "deductible": deductible,
            "deductible_display": _money_display(deductible),
            "requires": self.requires(plan_id),
            "coverage_style": "broad_exclusions" if components["broad"] else "explicit_components",
            "covered_components": components["items"],
            "coverage_wording": components.get("wording"),
            "exclusions": self.exclusions(plan_id),
            "explicitly_excluded_components": self.explicitly_excluded_components(plan_id),
            "inherits_from": self.inherited_from(plan_id),
            "options_available": self.options_available(plan_id),
        }

    def option_facts(self, option_id: str) -> Dict[str, Any]:
        option = self.options.get(option_id) or {}
        return {
            "id": option_id,
            "covers": list(option.get("covers", [])),
            "excludes": list(option.get("excludes", [])),
        }