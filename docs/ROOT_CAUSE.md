# Root-cause diagnosis of the starter assistant

The starter module (`starter/assistant.py`) was 33 lines and contained
roughly a dozen distinct defects. They are grouped here by the symptom a
reviewer would observe and the mechanism that caused it.

The original file is preserved in git history; the line references below
are to that original.

## Summary table

| # | Symptom observed | Root cause in starter code | Remedy implemented |
| --- | --- | --- | --- |
| 1 | A plan the customer cannot see gets recommended | `candidate_ids = state.get("eligible_ids", list(PLANS))` read `eligible_ids` only. `visible_ids` was **never read anywhere in the file**, so the "displayed set" restriction was entirely absent | `NormalizedState.allowed_ids` = `eligible_ids ∩ visible_ids`; every plan in the fact pack is drawn from that intersection (`coverage_assistant/state.py`) |
| 2 | When `eligible_ids` is absent, the whole catalogue is offered | `state.get("eligible_ids", list(PLANS))` defaults to *every* plan in the catalogue, so a missing key widened authorization instead of narrowing it | `normalize_state` treats a missing key as **empty**, and records a warning. A missing key can never widen the allowed set (`tests/test_state.py::test_missing_visible_ids_does_not_widen_to_whole_catalog`) |
| 3 | `IndexError` on an empty candidate list | `candidate_ids[0]` with no length check | Referent resolution never indexes blindly; an empty allowed set produces a graceful "no plans are currently available to you" answer (`tests/test_adversarial.py::test_empty_state_does_not_crash`) |
| 4 | The assistant keeps answering about a stale plan | `plan_id = self.last_plan_id or state.get("selected_id") or candidate_ids[0]` puts `self.last_plan_id` **first**, so a plan discussed two turns ago outranks the customer's current selection | Precedence is now: explicitly named plan → current `selected_id` → most recent plan → the single allowed plan (`resolve_referent`). A selection change is treated as an event, not a suggestion (`tests/test_multiturn.py::test_selection_change_is_reflected_on_next_turn`) |
| 5 | Unknown plan ids are answered as if they existed | `PLANS.get(plan_id, {})` returns an empty dict, which then flows into the prompt and the response as `plan.get('name', 'the best plan')` | Unknown ids are dropped during normalization with an explicit warning; a blocked plan can only be mentioned as a refusal, never described (`tests/test_state.py::test_unknown_plan_ids_are_dropped_with_warning`) |
| 6 | "It covers everything you asked about" | The offline path was a hard-coded template that unconditionally claimed total coverage, regardless of the catalog | The offline path renders a catalog-derived answer and is labelled `OFFLINE_DETERMINISTIC - NOT AN LLM`. Universal-promise detection is negation-aware and runs on the final answer (`coverage_assistant/offline_render.py`, `coverage_assistant/facts.py::detect_universal_claim`) |
| 7 | Ungrounded claims about price, deductible, components | The prompt embedded the raw `plan` dict and trusted the model to read it correctly. Nothing checked the output | A **fact pack** is built in code and is the only coverage information given to the model. The final answer is re-validated against the catalog: any dollar amount that does not match an allowed plan or a catalog benefit is rejected (`coverage_assistant/guardrails.py::validate_answer`) |
| 8 | Invisible plans leak their price and components | Because `visible_ids` was ignored, `P-EXCL` was a normal candidate and the model was free to describe it | The fact pack contains **only** allowed plans. A blocked plan appears solely as an availability note with no price, components or deductible, and the validator rejects any mention of it outside a refusal sentence |
| 9 | An offered option is described as if it were purchased | `selected_options` was never read. `state` was interpolated into the prompt as a whole, so the model could not tell an offered option from a purchased one | `purchased_options` and `offered_options` are separate fields in the fact pack, and the validator rejects an answer that asserts coverage for a component whose option was not purchased (`tests/test_guardrails.py::test_unpurchased_option_coverage_rejected`) |
| 10 | The Wrap plan inherits powertrain coverage | Inheritance was never resolved; the raw dict for `P-WRAP` was shown to the model, and its `components` list looked similar to `P-PLUS` | `Catalog.inherited_from` resolves inheritance explicitly. `P-WRAP` has no `inherits` key, so it inherits nothing, and its `explicitly_excludes` list is surfaced as an exclusion (`tests/test_catalog.py::test_wrap_does_not_inherit_base`) |
| 11 | Benefits are described as guaranteed | No benefit data was checked at all | Benefit caps and conditions come from the catalog. The validator rejects guarantee phrasing such as "always get a rental car" while allowing conditional wording (`tests/test_guardrails.py::test_guaranteed_rental_rejected`) |
| 12 | The assistant approves claims | Nothing prevented it | Guarantee and claims-decision phrasing is rejected, and the catalog's `claims_conditions` are surfaced instead |
| 13 | Conversation history grows without limit | `self.history.append(question)` with no trimming, and the whole history was re-sent in every prompt | History is bounded to 6 turns, prior turns are truncated and delimited as `[previous turn]`, and the question itself is length-capped (`coverage_assistant/prompts.py::build_messages`) |
| 14 | A provider outage crashes the request | `self.model(prompt)` was called with no error handling; any exception propagated to the caller | Provider errors are caught, reported honestly inside the answer, and recorded in the trace. The assistant never presents a canned answer as if a model had written it (`tests/test_adversarial.py::test_provider_error_is_reported_honestly`) |
| 15 | No spend control | No call or token limits | `LLM_MAX_TOKENS` caps tokens per call and `LLM_MAX_CALLS` caps calls per session; exceeding the cap raises `SpendCapError` (`tests/test_live_provider.py::test_spend_cap_stops_further_calls`) |
| 16 | Malformed state raises | `state.get(...)` assumed a dict | `normalize_state` accepts any input, dropping unknown ids and recording warnings, and never raises (`tests/test_adversarial.py::test_garbage_state_does_not_crash`) |

## Why the offline starter was not simply "improved"

The original offline branch could not be repaired by adding conditionals
because it was a single hard-coded sentence with no relationship to the
catalog. It was replaced with a deterministic renderer
(`coverage_assistant/offline_render.py`) that derives its answer from the
same fact pack the model receives. That makes the offline mode useful as a
*test oracle*: it is a reference implementation of "what a correct answer
looks like", which is what makes the credential-free safety suite
meaningful.

The label `OFFLINE_DETERMINISTIC - NOT AN LLM` is prepended to every
offline answer so it can never be mistaken for model output. This is a
hard requirement from the brief, and it is asserted in the test suite.

## Class of defect, summarised

1. **Authorization defaults were inverted.** Absent or unknown state
   widened access instead of narrowing it. The single most damaging
   pattern, because it fails open.
2. **Conversation memory was treated as authoritative.** Cached state
   (`last_plan_id`) was consulted before live state.
3. **The model was trusted to read structured data correctly.** Prices,
   inheritance, option status and benefit caps were all left to the
   model's comprehension.
4. **Safety lived only in the prompt.** There was no prompt at all in
   the starter, and no post-generation check.
5. **There were no tests.** The supplied smoke test asserted only that
   the return value was a non-empty string.
