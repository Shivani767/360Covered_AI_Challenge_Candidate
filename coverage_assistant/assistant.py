"""The coverage assistant: the public entry point.

Flow for one turn:

    raw state
      -> normalize_state        (validate; drop unknown ids; never widen)
      -> resolve_referent        (which plan is "it" right now?)
      -> detect_intent           (what shape of answer is needed?)
      -> build_fact_pack         (authorized, catalog-derived facts)
      -> provider.complete       (LLM, or deterministic offline adapter)
      -> validate_answer         (code-level check of the model's output)
      -> repair / deterministic fallback if validation failed

Everything above the provider line is deterministic and unit-testable
without a key or a network. The provider is the only non-deterministic
part, and its output is never trusted without ``validate_answer``.

The public API is ``CoverageAssistant.answer(question, state) -> str``,
which keeps the interface of the supplied starter module and the reviewer
harness.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .catalog import Catalog
from .facts import build_fact_pack, detect_intent
from .guardrails import authorized_scope, validate_answer
from .llm import (
    BaseProvider,
    MissingCredentialError,
    OfflineDeterministicProvider,
    ProviderConfig,
    ProviderError,
    build_provider,
)
from .offline_render import OFFLINE_LABEL, render_answer
from .prompts import PROMPT_VERSION, build_messages

SAFE_FALLBACK = "SAFE_FALLBACK (deterministic)"
from .state import normalize_state, resolve_referent

MAX_HISTORY_TURNS = 6


@dataclass
class TurnTrace:
    """Everything that happened in one turn, for debugging and eval."""

    question: str
    mode: str
    intent: str = ""
    referent_plan_id: Optional[str] = None
    referent_source: str = ""
    allowed_plan_ids: List[str] = field(default_factory=list)
    fact_pack: Dict[str, Any] = field(default_factory=dict)
    raw_answer: str = ""
    answer: str = ""
    violations: List[str] = field(default_factory=list)
    repaired: bool = False
    fallback_used: bool = False
    error: Optional[str] = None
    provider_calls: int = 0
    prompt_version: str = PROMPT_VERSION
    # Violations of the answer that was actually delivered to the customer.
    # `violations` describes the *first draft* the model produced; when that
    # draft was rejected and repaired or replaced, the delivered answer can be
    # clean even though `violations` is non-empty. `final_violations` is empty
    # exactly when the delivered answer passed the guardrails.
    final_violations: List[str] = field(default_factory=list)

    @property
    def final_ok(self) -> bool:
        """True when the answer the customer received passed validation."""
        return not self.final_violations

    def as_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "mode": self.mode,
            "intent": self.intent,
            "referent_plan_id": self.referent_plan_id,
            "referent_source": self.referent_source,
            "allowed_plan_ids": list(self.allowed_plan_ids),
            "violations": list(self.violations),
            "final_violations": list(self.final_violations),
            "final_ok": self.final_ok,
            "repaired": self.repaired,
            "fallback_used": self.fallback_used,
            "error": self.error,
            "prompt_version": self.prompt_version,
        }


class CoverageAssistant:
    """Coverage explanation assistant.

    Parameters
    ----------
    model:
        Optional callable ``(prompt: str) -> str`` kept for compatibility
        with the starter module. When supplied it is used as the provider.
    mode:
        "offline" (default) for the deterministic adapter, "live" for a real
        LLM call.
    provider:
        An explicit provider instance; overrides ``mode``.
    """

    def __init__(
        self,
        model: Optional[Any] = None,
        mode: Optional[str] = None,
        provider: Optional[BaseProvider] = None,
        catalog: Optional[Catalog] = None,
        config: Optional[ProviderConfig] = None,
    ) -> None:
        self.catalog = catalog or Catalog.load()
        self.mode = (mode or os.environ.get("ASSISTANT_MODE") or "offline").lower()
        self.history: List[Dict[str, str]] = []
        self.recent_plan_ids: List[str] = []
        self.last_trace: Optional[TurnTrace] = None
        self.config = config

        if provider is not None:
            self.provider = provider
        elif model is not None:
            self.provider = _CallableProvider(model)
        else:
            self.provider = build_provider(self.mode, config)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    @property
    def is_live_llm(self) -> bool:
        return bool(getattr(self.provider, "is_llm", False))

    @property
    def mode_label(self) -> str:
        """Human-readable description of what produced the answers.

        Must stay accurate: it is the reviewer's evidence that a live run
        really used a model.
        """
        if not self.is_live_llm:
            return "OFFLINE_DETERMINISTIC - NOT AN LLM"
        name = getattr(self.provider, "name", "provider")
        model = getattr(getattr(self.provider, "config", None), "model", None)
        if not model:
            model = getattr(self.config, "model", None)
        suffix = f" ({model})" if model else ""
        return f"LIVE LLM ({name}{suffix})"

    def answer(self, question: str, state: Any) -> str:
        """Answer a customer question given application state.

        Always returns a string. Provider failures are reported inside the
        answer text with a clear, honest message rather than an exception,
        so the reviewer UI keeps working and never mistakes a failure for a
        successful model response.
        """
        trace = self._answer_with_trace(question, state)
        self.last_trace = trace
        return trace.answer

    def reset(self) -> None:
        """Clear conversation history and referent memory."""
        self.history = []
        self.recent_plan_ids = []

    # ------------------------------------------------------------------
    # core
    # ------------------------------------------------------------------
    def _answer_with_trace(self, question: str, state: Any) -> TurnTrace:
        trace = TurnTrace(question=question or "", mode=self.mode_label)

        norm = normalize_state(state, self.catalog)
        intent = detect_intent(question or "")
        referent = resolve_referent(
            question or "", norm, self.catalog, self.recent_plan_ids
        )
        fact_pack = build_fact_pack(
            question or "", norm, referent, self.catalog, intent
        )

        trace.intent = intent.primary
        trace.referent_plan_id = referent.plan_id
        trace.referent_source = referent.source
        trace.allowed_plan_ids = list(fact_pack["allowed_plan_ids"])
        trace.fact_pack = fact_pack

        # The authorization scope is used by the validator, not by the
        # model: it lists every plan id in the catalog, which the model has
        # no need to see.

        messages = build_messages(question or "", fact_pack, self.history)

        try:
            raw = self.provider.complete(messages)
        except MissingCredentialError as exc:
            trace.error = str(exc)
            trace.final_violations = ["provider error: no model-written answer was produced"]
            trace.answer = (
                "I could not reach a language model because no API credentials are "
                f"configured ({exc}). No answer has been generated."
            )
            self._record(trace, referent, norm)
            return trace
        except ProviderError as exc:
            trace.error = str(exc)
            trace.final_violations = ["provider error: no model-written answer was produced"]
            trace.answer = (
                "The language model could not be reached, so I do not have a "
                f"model-written answer for you. Provider error: {exc}"
            )
            self._record(trace, referent, norm)
            return trace
        except Exception as exc:  # defensive: never crash the reviewer UI
            trace.error = f"{type(exc).__name__}: {exc}"
            trace.final_violations = ["provider error: no model-written answer was produced"]
            trace.answer = (
                "The language model could not be reached, so I do not have a "
                f"model-written answer for you. Provider error: {exc}"
            )
            self._record(trace, referent, norm)
            return trace

        trace.raw_answer = raw

        result = validate_answer(raw, norm, self.catalog, fact_pack)
        trace.violations = list(result.violations)

        if result.ok:
            trace.answer = raw
            trace.final_violations = []
            trace.provider_calls = getattr(self.provider, "calls", 0)
            self._record(trace, referent, norm)
            return trace

        # Attempt one repair, then fall back to the deterministic renderer.
        repaired = self._repair(messages, result.violations)
        if repaired is not None:
            second = validate_answer(repaired, norm, self.catalog, fact_pack)
            if second.ok:
                trace.repaired = True
                trace.violations = list(result.violations)
                trace.answer = repaired
                # The delivered answer passed the guardrails; the draft that
                # was rejected is still recorded in `violations`.
                trace.final_violations = []
                trace.provider_calls = getattr(self.provider, "calls", 0)
                self._record(trace, referent, norm)
                return trace

        trace.fallback_used = True
        body = render_answer(fact_pack)
        # In live mode, the deterministic fallback must carry its own label
        # so it is never mistaken for model output. Offline mode already
        # carries OFFLINE_DETERMINISTIC from render_answer.
        if self.is_live_llm:
            trace.answer = f"{SAFE_FALLBACK}\n\n{body}"
        else:
            trace.answer = body
        # The deterministic fallback is rendered from the fact pack, so it is
        # grounded by construction; it is still validated so the trace states
        # exactly what the customer received.
        trace.final_violations = list(
            validate_answer(trace.answer, norm, self.catalog, fact_pack).violations
        )
        trace.provider_calls = getattr(self.provider, "calls", 0)
        self._record(trace, referent, norm)
        return trace

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _repair(self, messages: List[Dict[str, str]], violations: List[str]) -> Optional[str]:
        """Ask the model once more, telling it exactly what it got wrong."""
        if not getattr(self.provider, "is_llm", False):
            return None
        repair_messages = list(messages)
        repair_messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous answer was rejected by the automated safety check. "
                    "Problems found:\n- "
                    + "\n- ".join(violations)
                    + "\n\nRewrite the answer so that every statement is supported by "
                    "the FACT PACK, and do not make any universal coverage promise."
                ),
            }
        )
        try:
            return self.provider.complete(repair_messages)
        except Exception:
            return None

    def _record(self, trace: TurnTrace, referent: Any, norm: Any) -> None:
        """Update conversation memory after a turn."""
        self.history.append({"role": "user", "content": trace.question})
        self.history.append({"role": "assistant", "content": trace.answer})
        if len(self.history) > MAX_HISTORY_TURNS * 2:
            self.history = self.history[-MAX_HISTORY_TURNS * 2 :]

        if referent.plan_id and referent.plan_id in norm.allowed_ids:
            if referent.plan_id in self.recent_plan_ids:
                self.recent_plan_ids.remove(referent.plan_id)
            self.recent_plan_ids.insert(0, referent.plan_id)
            self.recent_plan_ids = self.recent_plan_ids[:5]


class _CallableProvider(BaseProvider):
    """Adapter for the starter module's ``model(prompt) -> str`` callable."""

    name = "callable"

    def __init__(self, func: Any) -> None:
        super().__init__(ProviderConfig(provider="callable"))
        self.func = func

    def complete(self, messages: List[Dict[str, str]]) -> str:
        self._check_budget()
        prompt = "\n\n".join(m.get("content", "") for m in messages)
        result = self.func(prompt)
        self.calls += 1
        return str(result)
