# Architecture and data flow

## Design principle

> The LLM explains. It never decides.

Every rule that affects what a customer is *allowed* to hear, and every
number they are told, is decided in Python code. The language model only
turns an authorized, catalog-derived fact pack into prose. If the model
disobeys, the answer is caught, repaired or replaced before the customer
sees it.

This is why the offline mode is not merely a fallback. The offline adapter
is a reference implementation of the same contract the live model must
satisfy, which is what makes the credential-free test suite meaningful.

## Data flow for one turn

```
  question (str)              state (dict)
        |                          |
        |                          v
        |            +-----------------------------+
        |            |  normalize_state()          |  validate, drop unknown ids,
        |            |  coverage_assistant/state.py|  never widen the allowed set
        |            +-----------------------------+
        |                          |
        |                          v
        |            +-----------------------------+
        |            |  allowed_ids =              |
        |            |      eligible ∩ visible      |  <-- authorization
        |            +-----------------------------+
        |                          |
        v                          v
  +-------------+        +---------------------+
  | detect_     |        | resolve_referent()  |  "it" -> the plan in play now
  | intent()    |        | state.py            |
  +-------------+        +---------------------+
        |                          |
        +------------+-------------+
                     v
        +-------------------------------+
        |  build_fact_pack()            |  facts.py - the ONLY coverage
        |  catalog + authorized state   |  information the model sees
        +-------------------------------+
                     |
                     v
        +-------------------------------+
        |  build_messages()             |  prompts.py - rules + fact pack
        |  (bounded history)            |
        +-------------------------------+
                     |
                     v
        +-------------------------------+
        |  provider.complete()          |  llm.py - live LLM, or the
        |  (token cap, call cap)        |  deterministic offline adapter
        +-------------------------------+
                     |
                     v
        +-------------------------------+
        |  validate_answer()            |  guardrails.py - universal
        |  guardrails.py                |  promise? blocked plan? wrong
        |                               |  amount? unpurchased option?
        +-------------------------------+
           | ok            | failed
           |               v
           |      +-------------------+
           |      | one repair call   |
           |      +-------------------+
           |        | ok        | failed
           |        v           v
           |    model answer   render_answer()  offline_render.py
           |                   deterministic, catalog-derived
           v
       +-------+
       | answer|
       +-------+
```

## Module map

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `coverage_assistant/catalog.py` | Load `data/plans.json`; resolve inheritance, exclusions, components, option facts, comparison order | - |
| `coverage_assistant/state.py` | Normalize raw state; compute `allowed_ids`; resolve the referent ("it", "that plan"); match option ids | `catalog` |
| `coverage_assistant/facts.py` | Detect intent; detect universal-promise phrasing; build the authorized fact pack | `catalog`, `state` |
| `coverage_assistant/prompts.py` | System rules + machine-readable fact pack; bounded history | - |
| `coverage_assistant/llm.py` | Provider adapters (OpenAI, Anthropic, OpenAI-compatible), offline adapter, retries, token/call caps | - |
| `coverage_assistant/guardrails.py` | Authorization scope; post-generation validation | `catalog`, `facts`, `state` |
| `coverage_assistant/offline_render.py` | Deterministic answer rendering from the fact pack | - |
| `coverage_assistant/assistant.py` | Orchestration: normalize -> resolve -> build -> call -> validate -> repair/fallback | all of the above |
| `coverage_assistant/cli.py` | Command-line entry point | `assistant`, `catalog` |
| `starter/assistant.py` | Backwards-compatible shim so the supplied harness and smoke test still work | `coverage_assistant` |
| `review_ui.py` | Local reviewer UI (standard library HTTP server) | `coverage_assistant` |

## The fact pack

The fact pack is the boundary between "what is true" and "what is said".
It is a plain JSON object, built in code, and it is the only coverage
information the model receives.

Key fields:

| Field | Meaning |
| --- | --- |
| `allowed_plans` | Full facts for plans in `eligible ∩ visible`, and nothing else |
| `selected_plan_id` | The plan the application says is selected (only if allowed) |
| `referent_plan` / `referent_source` | The plan the question is about, and how that was determined |
| `purchased_options` | Options actually bought |
| `offered_options` | Options available on the allowed plans |
| `option_status` | Per option: what it covers, what it excludes, whether it is purchased |
| `mentioned_components` | Catalog components named in the question (alias-resolved) |
| `benefits` | Benefit caps and conditions, verbatim from the catalog |
| `claims_conditions` | Administrator conditions, quoted from the catalog |
| `unavailable_plans` | Only plans the customer **named**, with an availability reason and no details |
| `blocked_plan_ids` | Plan ids the customer named that the assistant may not describe |

A plan the customer never mentions never appears in the fact pack, so the
model cannot drift into discussing the whole catalogue.

## Guardrail checks

`validate_answer` runs on every answer, live or offline:

1. **Empty answer** - rejected.
2. **Universal coverage promise** - "covers everything", "bumper to
   bumper", "no exclusions", and similar. Detection is sentence-scoped and
   negation-aware, so "no plan covers everything" is *not* flagged.
3. **Guarantee / claims-decision language** - "always a rental car",
   "guaranteed", "your claim will be approved".
4. **Unauthorized plan reference** - a blocked plan may be named only in a
   sentence that states unavailability. Describing it is a violation.
5. **Fabricated amounts** - every dollar figure in the answer must match
   an allowed plan's price or deductible, or a catalog benefit cap. Amounts
   belonging to a blocked plan are rejected even if they are catalog
   numbers.
6. **Unpurchased option asserted as in force** - sentence-scoped, so
   "would be covered by electronics_plus, which you have not purchased" is
   accepted while "your navigation screen is covered" is not.
7. **Wrong deductible for the plan in question** - cross-checked against
   the referent's catalog value.

On failure the assistant makes **one** repair call that names the
violations. If the repaired answer still fails, it is replaced by
`render_answer()`, a deterministic catalog-derived answer. The customer
never receives an answer that failed validation.

## State changes are events, not suggestions

`selected_id` is read fresh on every turn. The conversation history is used
only to resolve anaphora ("what is *its* deductible?") when the state
gives no other signal. Consequently:

* changing the selected plan mid-conversation changes the next answer
  (`tests/test_multiturn.py::test_selection_change_is_reflected_on_next_turn`),
* making a plan invisible removes it from the next answer entirely
  (`test_plan_is_not_sticky_after_visibility_change`),
* purchasing an option changes the next answer about that option
  (`test_option_purchase_is_reflected`).

## Trust boundaries

| Boundary | Protection |
| --- | --- |
| Customer question -> model | The question is the last message, length-capped, and prefixed with system rules that refuse instruction-following requests |
| Prior turns -> model | Bounded to 6 turns, truncated to 1000 characters, prefixed `[previous turn]` so a prior turn cannot pose as a system instruction |
| Model output -> customer | Full validation pass; repair; deterministic fallback |
| Catalog -> model | The fact pack is the only channel; the model never sees the raw catalog file or the blocked plan list |
| Environment -> code | API keys are read from the environment only and are never written to a file or a log |
