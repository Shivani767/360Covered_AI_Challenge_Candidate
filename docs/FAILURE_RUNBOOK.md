# Diagnosing an intermittent false claim after deployment

The brief asks how I would diagnose an intermittent false claim that
appears in production after a deploy. This is the runbook I would actually
follow. The short version: **do not start by looking at the model.** The
model is the least likely thing to be the cause of an *intermittent* false
claim, because a model that is confidently wrong tends to be confidently
wrong every time. Intermittency points at state, ordering, or context.

## The core principle

A false claim that is intermittent has a variable input. Find the variable
input first, then the code path that failed to defend against it.

Two failure families are worth separating before you start:

| Family | Signature | Usual cause |
| --- | --- | --- |
| **Guardrail bypass** | The violation is in the answer text | The model's output was accepted because the rule did not fire, or the rule fired and the repair produced the same violation again |
| **Fact-pack corruption** | The answer is wrong about a fact that *was* in the fact pack | The model read the pack correctly but the pack itself was wrong |
| **State/ordering bug** | The answer is wrong about *which plan* is being discussed | A race, a stale cache, or a referent resolved against the wrong turn |

Most "the AI hallucinated" reports are actually the third family.

## Step 1 - Reproduce and capture the exact inputs

**Never** investigate from the customer's paraphrase. Capture the exact
turn that produced the false claim.

This project already records most of what you need on every turn. The
`TurnTrace` object holds:

* `question` - the exact question as sent
* `mode` - offline or live, and which model
* `intent` - the detected intent
* `referent_plan_id` and `referent_source` - which plan the answer was
  about and *why* it was chosen (`explicit`, `selected`, `recent`,
  `only_allowed`)
* `allowed_plan_ids` - the authorized set at that moment
* `violations` - what the guardrail caught
* `repaired` / `fallback_used` - whether the answer was rewritten or
  replaced
* `error` - a provider failure, if any

**What to add for production:** persist the trace alongside the answer,
plus the raw provider response, the raw fact pack, the model id, the
prompt version, and a request id. Without the raw model output you cannot
tell a guardrail bypass from a fact-pack problem.

Then reproduce it with the deterministic adapter:

```bash
python -m coverage_assistant.cli -q "<the exact question>" \
  --state '<the exact state JSON>' --show-trace
```

If the offline adapter produces a *correct* answer for the same inputs, the
bug is in the model output or the validation. If it produces the *same
false claim*, the bug is upstream, in the fact pack or the state.

That one command splits the investigation in half.

## Step 2 - Is the fact pack correct?

Diff the fact pack captured in production against what the catalogue and
state should have produced.

```python
from coverage_assistant.catalog import Catalog
from coverage_assistant.facts import build_fact_pack, detect_intent
from coverage_assistant.state import normalize_state, resolve_referent

catalog = Catalog.load()
norm = normalize_state(state, catalog)
intent = detect_intent(question)
referent = resolve_referent(question, norm, catalog)
pack = build_fact_pack(question, norm, referent, catalog, intent)
```

Check, in this order:

1. **`allowed_plan_ids`** - is it exactly `eligible ∩ visible`? A plan that
   should not be there means an authorization bug, not a model bug.
2. **`referent_plan_id`** - is it the plan the customer meant? Look at
   `referent_source`. If it says `recent`, the anaphora resolution picked
   a stale plan.
3. **The specific numbers in the claim** - is the false claim about a
   value that is *wrong in the pack*, or about a value that is *absent from
   the pack*?
   * Wrong in the pack -> a catalogue resolution bug (inheritance,
     exclusions, option status).
   * Absent from the pack -> the model invented it, and the guardrail
     should have caught it.
4. **`purchased_options`** - if the claim asserts coverage for an option
   the customer did not buy, check whether the state at that moment
   actually contained the option.

## Step 3 - Did the guardrail fire?

If the false claim reached the customer, the validator either did not fire
or was bypassed.

* `violations` is empty in the trace -> the validator missed it. Add a
  case to `tests/test_guardrails.py` with the exact offending sentence,
  then fix the rule. This is a coverage gap, not a model failure.
* `violations` is non-empty but `fallback_used` is `False` and
  `repaired` is `True` -> **the repair produced the same violation again**
  and the repaired answer was accepted. That means `validate_answer` was
  not applied to the repair result, or the repair path bypasses it. Check
  `assistant._repair` and the second `validate_answer` call.
* `violations` is non-empty and `fallback_used` is `True` -> the fallback
  produced the false claim. The deterministic renderer has a bug; it is
  the most testable component in the system and the failure is reproducible
  with no key.

## Step 4 - Narrow the variable

Intermittency means something varies. In order of likelihood:

1. **State changed between turns.** Did the customer change their
   selection, purchase an option, or lose visibility of a plan between the
   question and the answer? Compare the `allowed_plan_ids` and
   `referent_plan_id` of the failing turn with the turn before it. If the
   referent source flipped from `selected` to `recent`, the stale-plan
   class of bug is back.
2. **Conversation history length.** The transcript is bounded at six
   turns. Does the failure only appear in long conversations? Test by
   replaying the same question with the history truncated.
3. **Provider variance.** Same inputs, different answer? Replay the failing
   input several times against the same model and temperature. If the
   outcome varies, the validator is not strict enough for that claim type.
   Add the failing output as a test case.
4. **Model or prompt version.** Did a deploy change the model id, the
   prompt, or the fact-pack schema? Compare the deployed version against
   the previous one; the prompt is versioned with the code.
5. **Concurrency.** Two requests sharing one assistant instance would
   corrupt `self.history` and `self.recent_plan_ids`. **This is a real
   hazard in this design**: `CoverageAssistant` holds mutable conversation
   state and is not thread-safe. In production, one assistant instance per
   conversation, or a lock. If the failure correlates with concurrent
   requests, this is the cause.

## Step 5 - Confirm with a regression test

Whichever cause you find, the fix is not complete until:

* a failing case exists in `tests/test_guardrails.py` (if the validator
  missed it) or `tests/test_multiturn.py` (if it was a state or ordering
  bug);
* the test fails before the fix and passes after it;
* the same input, replayed through the deterministic adapter, produces the
  expected behaviour.

Then re-run the whole suite and `python scripts/run_eval.py`, and attach the
regenerated report to the change.

## Guardrails against this recurring

* **Trace everything.** `TurnTrace` already carries the intent, referent,
  allowed set and violations. Persist it in production. A false claim
  without a trace is close to undebuggable.
* **Version the prompt.** `prompts.SYSTEM_RULES` is a constant; give it a
  version string and record it in the trace, so a claim can be tied to the
  prompt that produced it.
* **Shadow the deterministic adapter.** Run it alongside the live model in
  production. Any turn where the live answer and the deterministic answer
  disagree in a way the validator would care about is a near-miss. This is
  the cheapest possible early-warning system, and it needs no ground-truth
  labels.
* **Alert on the guardrail counters.** Rate of `violations`,
  `repaired` and `fallback_used` should be monitored. A spike in
  `fallback_used` means the live model is drifting and customers are
  getting templated answers.
* **Treat a fallback as an incident.** A customer receiving the
  deterministic fallback is receiving a worse experience. If that rate is
  not near zero, treat it as a defect in its own right.

## What I would not do

* I would not start by changing the prompt and redeploying. If the false
  claim is intermittent, a prompt change will usually make it *less*
  reproducible and therefore less diagnosable.
* I would not "fix" it by adding the specific forbidden phrasing to the
  blocklist without a regression test. That converts a safety failure into
  a maintenance burden and hides the real cause.
* I would not disable the guardrail to reduce the fallback rate. The
  fallback is the reason the system is safe; a fallback spike is a signal
  to investigate, not to remove.
