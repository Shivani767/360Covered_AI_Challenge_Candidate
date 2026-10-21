# AI Coverage Assistant - candidate submission

A reliable, independently runnable coverage-explanation assistant for the
synthetic 360Covered catalogue. The LLM explains coverage; **it never
decides what a customer may hear**. All authorization, all contract facts
and all safety checks live in Python code, not in prompts.

- Root-cause diagnosis of the starter code: [`docs/ROOT_CAUSE.md`](docs/ROOT_CAUSE.md)
- Architecture and data flow: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Example conversations: [`docs/EXAMPLE_CONVERSATIONS.md`](docs/EXAMPLE_CONVERSATIONS.md)
- Intermittent-false-claim runbook: [`docs/FAILURE_RUNBOOK.md`](docs/FAILURE_RUNBOOK.md)
- Evaluation results: [`reports/eval_report.md`](reports/eval_report.md)

---

## 1. Quick start (reviewer machine, no credentials)

Requirements: **Python 3.9 or newer**. No third-party packages, no
installation step, no virtualenv required. The project uses only the
Python standard library.

```bash
git clone https://github.com/Shivani767/360Covered_AI_Challenge_Candidate.git
cd 360Covered_AI_Challenge_Candidate

# 1. Run the whole evaluation suite (no API key needed)
python -m unittest discover -s tests -v

# 2. Generate the readable results report
python scripts/run_eval.py

# 3. Launch the reviewer UI
python review_ui.py
# then open http://127.0.0.1:8765
```

That is the whole setup. `python --version` should print 3.9 or higher.

> If `python` is not on your PATH, substitute `python3`. Everything else is
> identical.

### One-command start and test

```bash
python scripts/run_eval.py && python review_ui.py
```

## 2. How to use it (three ways)

### (a) The reviewer UI - interactive

```bash
python review_ui.py
# then open http://127.0.0.1:8765
```

Set the customer state on the left (eligible / visible plans, selected plan,
purchased options), type a question, and press **Ask**. The page shows the
answer plus the intent, the resolved referent, the allowed plan ids and a
guardrail badge. **Reset conversation** clears the transcript and the
anaphora memory. The port can be changed with `REVIEW_UI_PORT`.

### (b) The command line - one question, one answer

```bash
# Offline (no credentials, deterministic)
python -m coverage_assistant.cli -q "What is the deductible for CoreDrive Plus?"

# Live LLM (Ollama, no key needed)
ASSISTANT_MODE=live LLM_PROVIDER=openai-compatible \
LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:3b \
  python -m coverage_assistant.cli -q "What does DriveWrap cover?" --show-trace

# Inspect the catalogue
python -m coverage_assistant.cli --list-plans
```

`--state` takes a JSON object if you want to drive it from a script:

```bash
python -m coverage_assistant.cli -q "What is my deductible?" \
  --state '{"eligible_ids":["P-PLUS"],"visible_ids":["P-PLUS"],"selected_id":"P-PLUS","selected_options":[]}'
```

`--show-trace` prints the internal decision record: intent, referent, the
allowed plan ids, the first-draft violations, the delivered answer's
violations (`final_violations`), and whether the answer was repaired or
fell back to the deterministic template.

### (c) As a library

```python
from coverage_assistant import CoverageAssistant

state = {
    "eligible_ids": ["P-BASE", "P-PLUS"],
    "visible_ids": ["P-BASE", "P-PLUS"],
    "selected_id": "P-PLUS",
    "selected_options": [],
}

bot = CoverageAssistant(mode="offline")   # or mode="live"
print(bot.answer("What is my deductible?", state))
print(bot.last_trace.as_dict())           # full decision record
```

The original import path still works, so the supplied harness and smoke
test run unchanged:

```python
from starter.assistant import CoverageAssistant
```

## 3. Architecture at a glance

> **The LLM explains. It never decides.**

Every rule that affects what a customer is *allowed* to hear, and every
number they are told, is decided in Python code. The model only turns an
authorized, catalogue-derived fact pack into prose. If the model disobeys,
the answer is caught, repaired or replaced **before** the customer sees it.

### The pipeline for one turn

```
 question (str)                 state (dict)
       |                             |
       |                             v
       |              +-------------------------------+
       |              | normalize_state()             |  drop unknown ids,
       |              | state.py                      |  never widen the set
       |              +-------------------------------+
       |                             |
       |                             v
       |              +-------------------------------+
       |              | allowed = eligible INTERSECT  |  <-- authorization
       |              |          visible               |      in code, not prompts
       |              +-------------------------------+
       |                             |
       v                             v
 +-------------+            +----------------------+
 | detect_     |            | resolve_referent()   |  "its" -> the plan in play
 | intent()    |            | state.py             |
 | facts.py    |            +----------------------+
 +-------------+
       |                             |
       +-------------+---------------+
                     v
        +-------------------------------+
        | build_fact_pack()             |  the ONLY coverage information
        | catalog + authorized state    |  the model ever sees
        +-------------------------------+
                     |
                     v
        +-------------------------------+
        | build_messages()              |  system rules + fact pack
        | prompts.py (bounded history)  |  + bounded prior turns
        +-------------------------------+
                     |
                     v
        +-------------------------------+
        | provider.complete()           |  llm.py: live LLM or the
        | (token cap, call cap)         |  deterministic offline adapter
        +-------------------------------+
                     |
                     v
        +-------------------------------+
        | validate_answer()             |  guardrails.py
        +-------------------------------+
            |                 |
       ok   |                 | fail
            v                 v
      deliver as-is     +------------------------+
                       | 1) repair: one more     |  named violations
                       |    model call            |
                       | 2) validate again       |
                       +------------------------+
                            |            |
                       ok   |            | fail
                            v            v
                      deliver      +------------------+
                      (REPAIRED)   | SAFE_FALLBACK    |  deterministic,
                                   | (deterministic)  |  catalog-grounded
                                   +------------------+
```

### The modules that matter

| Module | Responsibility |
| --- | --- |
| `coverage_assistant/state.py` | Normalizes the state, computes `eligible ∩ visible`, resolves the referent ("it", "that plan") |
| `coverage_assistant/facts.py` | Detects the intent and builds the **fact pack**: a JSON object containing only the plans the customer may hear about |
| `coverage_assistant/prompts.py` | Assembles the system rules, the fact pack and the bounded history into model messages |
| `coverage_assistant/llm.py` | Provider adapters (OpenAI, Anthropic, any OpenAI-compatible server), retries, token/call caps |
| `coverage_assistant/guardrails.py` | Validates the generated answer against the catalogue before delivery |
| `coverage_assistant/assistant.py` | Orchestrates the turn: fact pack -> model -> validate -> repair -> fallback -> trace |

### The fact pack - the boundary between truth and speech

The fact pack is built in code and is the only coverage information the
model receives. A plan the customer never mentions never appears in it, so
the model cannot drift into discussing the whole catalogue. It carries:

| Field | Meaning |
| --- | --- |
| `allowed_plans` | Full facts for plans in `eligible ∩ visible`, and nothing else |
| `selected_plan_id` | The plan the application says is selected (only if allowed) |
| `referent_plan` / `referent_source` | The plan the question is about, and how that was determined |
| `purchased_options` / `offered_options` | Options actually bought vs. merely available |
| `mentioned_components` | Catalogue components named in the question (alias-resolved) |
| `benefits` / `claims_conditions` | Benefit caps and conditions, quoted verbatim from the catalogue |
| `unavailable_plans` | Only plans the customer **named**, with a reason and no details |
| `blocked_plan_ids` | Plan ids the customer named that the assistant may not describe |

### The guardrails - eight checks on every answer

`validate_answer()` runs on every answer, live or offline:

1. **Empty answer** - rejected.
2. **Universal coverage promise** - "covers everything", "bumper to bumper",
   "every part is covered". Sentence-scoped and negation-aware, so "no plan
   covers everything" is *not* flagged.
3. **Guarantee / claims-decision language** - "always a rental car",
   "guaranteed", "your claim will be approved".
4. **Unauthorized plan reference** - a blocked plan may be named only in a
   sentence that states unavailability. Describing it is a violation.
5. **Fabricated amounts** - every dollar figure must match an allowed
   plan's price or deductible, or a catalogue benefit cap. Amounts that
   belong to a blocked plan are rejected even if they are catalogue numbers.
6. **Unpurchased option asserted as in force** - "would be covered by
   electronics_plus, which you have not purchased" is accepted; "your
   navigation screen is covered" is not.
7. **Wrong deductible for the plan in question** - cross-checked against the
   referent's catalogue value.
8. **Coverage claim for an excluded part** - claiming that DriveWrap covers
   the engine, or dismissing an exclusion ("the exclusion does not apply",
   "your engine is not excluded"), is rejected.

### Repair, then fallback

On failure the assistant makes **one** repair call that names the specific
violations. If the repaired answer still fails, it is replaced by a
deterministic, catalogue-derived answer. The customer never receives an
answer that failed validation. The reviewer UI reports the outcome of the
answer that was actually delivered as a `PASS` / `REPAIRED` / `FALLBACK` /
`FAIL` badge - see [section 5](#5-what-the-reviewer-can-do-in-the-ui).

### State changes are events, not suggestions

`selected_id` is read fresh on every turn; the conversation history is used
only to resolve anaphora when the state gives no other signal. Changing the
selected plan, making a plan invisible, or purchasing an option therefore
changes the very next answer.

### Trust boundaries

| Boundary | Protection |
| --- | --- |
| Customer question -> model | Length-capped, and prefixed with system rules that refuse instruction-following requests |
| Prior turns -> model | Bounded to 6 turns, truncated, prefixed `[previous turn]` so a prior turn cannot pose as a system instruction |
| Model output -> customer | Full validation pass, then repair, then deterministic fallback |
| Catalogue -> model | The fact pack is the only channel; the model never sees the raw catalogue file |
| Environment -> code | API keys are read from the environment only, and are never written to a file or a log |

The full data-flow diagram, module map and trust-boundary table are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 4. The three reviewer modes

The assistant supports three execution modes. They must not be confused with
each other.

| Mode | `ASSISTANT_MODE` | Model used | Credentials |
| --- | --- | --- | --- |
| **(a) Offline / deterministic** | `offline` (default) | **None.** A rule-based renderer | **None** |
| **(b) Live - OpenAI** | `live` | `gpt-4o-mini` (or `LLM_MODEL`) | `OPENAI_API_KEY` (your own) |
| **(c) Live - Local Llama via Ollama** | `live` | Installed Ollama model (`LLM_MODEL`) | **None** |

### Provider selection (`LLM_PROVIDER`)

| `LLM_PROVIDER` | `LLM_BASE_URL` | `OPENAI_API_KEY` | Result |
| --- | --- | --- | --- |
| *(unset)* | *(unset)* | set | OpenAI (`api.openai.com`) |
| *(unset)* | `http://localhost:11434/v1` | *(unset)* | Ollama (OpenAI-compatible) |
| `openai-compatible` | `http://localhost:11434/v1` | *(unset)* | Ollama (OpenAI-compatible) |
| `openai` | *(unset)* | set | OpenAI |
| `anthropic` | *(unset)* | `ANTHROPIC_API_KEY` | Anthropic |

### (a) Offline mode - credential-free

```bash
python review_ui.py                       # open http://127.0.0.1:8765
python -m unittest discover -s tests -v   # 145 cases, all offline
```

The offline adapter is a deterministic renderer over the same fact pack the
model receives. It proves the authorization, grounding and guardrail
behaviour. **It is not a language model and earns no credit for live model
behaviour.** Its role in this submission is to act as a test oracle and as
the safe fallback when a live model's output fails validation.

### (b) Live mode - OpenAI

Set **your own** key, then run with `ASSISTANT_MODE=live`:

```bash
export OPENAI_API_KEY=sk-...
export LLM_MODEL=gpt-4o-mini   # optional, defaults to gpt-4o-mini
ASSISTANT_MODE=live python review_ui.py
```

### (c) Live mode - Local Llama via Ollama

Ollama is a locally installed model server. No API key is required and no
per-request charges apply. The assistant reaches Ollama through its
OpenAI-compatible endpoint at `http://localhost:11434/v1`.

Prerequisites: Ollama installed and running, with at least one model
pulled (check with `ollama list`).

```bash
# 1. Confirm Ollama is running and see installed models
ollama list

# 2. Run the assistant with ASSISTANT_MODE=live, pointing at Ollama
export ASSISTANT_MODE=live
export LLM_PROVIDER=openai-compatible
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=<exact-model-name-from-ollama-list>   # e.g. qwen2.5:3b

python review_ui.py
# or from the command line:
python -m coverage_assistant.cli --mode live -q "What does DriveWrap cover?" --show-trace
```

No `OPENAI_API_KEY` is needed for Ollama mode. If Ollama is stopped, the
requested model is missing, or the endpoint is unreachable, the assistant
reports the error clearly and does not fabricate an answer.

The same works from the command line:

```bash
ASSISTANT_MODE=live python -m coverage_assistant.cli \
  -q "What does DriveWrap cover?" --show-trace
```

If no key is set (OpenAI mode) and no Ollama endpoint is reachable, live
mode fails with an explicit message and **no answer is fabricated**. The UI
shows the error rather than a plausible-looking reply.

### Expected usage and spend caps

Approximate cost per answer on `gpt-4o-mini` or `claude-3-5-haiku`: a
fraction of a cent. A full 20-turn review session costs **well under
$0.10**.

Two hard caps are enforced in code, not by convention:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_MAX_TOKENS` | `700` | Maximum tokens per call |
| `LLM_MAX_CALLS` | `40` | Maximum calls per assistant instance (session) |
| `LLM_TIMEOUT` | `30` | Per-request timeout in seconds |
| `LLM_MODEL` | provider default | Model id |

When the call cap is reached the assistant raises `SpendCapError` and says
so; it does not silently keep spending. Restarting the UI resets the
budget.

### Deterministic fallback (`SAFE_FALLBACK`)

When a live model's answer fails validation, the assistant attempts exactly
one repair. If repair also fails, it falls back to a deterministic,
catalog-grounded answer. In live mode this fallback answer is prefixed with
`SAFE_FALLBACK (deterministic)` so it is never mistaken for model output.
Offline mode answers carry the `OFFLINE_DETERMINISTIC - NOT AN LLM` label
instead. In every case the assistant never claims that a template was
written by a model.

## 5. What the reviewer can do in the UI

* Type **any** question.
* Toggle **eligible** and **visible** per plan between turns.
* Change the **selected plan** between turns (the reference implementation
  of a selection-change event).
* Edit the **selected options** field (`electronics_plus`, `exhaust_plus`,
  comma-separated).
* **Reset conversation**, which clears both the transcript and the
  anaphora memory.
* See, after every answer, the detected intent, the resolved referent, the
  allowed plan ids and the guardrail verdict.

The verdict badge describes the answer the customer actually received:

| Badge | Meaning |
| --- | --- |
| `PASS` | The model answer passed every guardrail rule as-is. |
| `REPAIRED` | The first draft was rejected, the model rewrote it, and the rewritten answer passed. The rejected draft's violations are listed underneath. |
| `FALLBACK` | The first draft and the repair both failed, so a deterministic catalog-grounded answer was delivered. It is labelled `SAFE_FALLBACK (deterministic)`. |
| `FAIL` | The delivered answer still violates a rule. This should not happen. |

The UI is a standard-library HTTP server bound to `127.0.0.1` only. There
is no auth, no database and no external dependency.

## 6. What was fixed, and why

The starter had sixteen distinct defects. The full table with code
behaviour and remedy is in [`docs/ROOT_CAUSE.md`](docs/ROOT_CAUSE.md). The
five that mattered most:

1. **`visible_ids` was never read.** A plan the customer could not see was
   a normal candidate. Now the allowed set is `eligible ∩ visible`.
2. **Missing state widened authorization.** `state.get("eligible_ids",
   list(PLANS))` defaulted to the whole catalogue. A missing key now means
   *empty*, never *everything*.
3. **Stale conversation state outranked live state.** `self.last_plan_id`
   was consulted before `selected_id`. The referent is now resolved from
   the current state first.
4. **Ungrounded claims.** The model saw a raw dict and was trusted to read
   it. It now sees a code-built fact pack, and its output is re-validated
   against the catalogue before the customer sees it.
5. **The offline template claimed "covers everything you asked about".**
   It now renders a catalog-derived answer, explicitly labelled as not an
   LLM.

## 7. Safety model in one paragraph

The allowed plan set is computed in code as `eligible_ids ∩ visible_ids`.
Only those plans enter the fact pack, so the model cannot describe an
invisible plan. After generation, the answer is checked for universal
coverage promises, guarantee and claims-decision language, unauthorised
plan references, dollar amounts that do not match the catalogue, coverage
claims for options that were offered but not purchased, and coverage claims
for a part the plan in question explicitly excludes (for example, claiming
that DriveWrap covers the engine). A failing
answer gets one repair attempt with the specific violations listed, and
then a deterministic catalogue-derived fallback. The model never has the
last word.

## 8. Test suite

```bash
python -m unittest discover -s tests -v
```

145 cases, all offline and all passing on a clean machine:

| File | Covers |
| --- | --- |
| `tests/test_catalog.py` | Inheritance, the Wrap special case, exclusionary-style plans, prices, ordering |
| `tests/test_state.py` | Authorization intersection, malformed state, referent resolution, option matching |
| `tests/test_guardrails.py` | Each validation rule, driven with deliberately unsafe candidate answers |
| `tests/test_scenarios.py` | All six supplied scenarios from `data/scenarios.json` |
| `tests/test_adversarial.py` | Prompt injection, malformed state, provider failures |
| `tests/test_multiturn.py` | Selection changes, visibility changes, option purchase/removal, bounded history |
| `tests/test_live_provider.py` | The live HTTP path against a local mock server: real request, fact pack on the wire, unsafe answer caught, spend cap, error surfacing |
| `tests/test_review_ui.py` | The reviewer UI over real HTTP: page and controls, `/ask` contract, the guardrail verdict for the delivered answer, reset |
| `tests/test_smoke.py` | The supplied smoke test, unchanged |
| `tests/test_sweep.py` | Property-style sweep over many questions x many states |

`tests/test_live_provider.py` starts a local mock HTTP server on a random
port. It needs no key and no network, and it exercises the same code path
as a real provider. `tests/test_review_ui.py` does the same for
`review_ui.py`, in offline mode.

## 9. Evaluation report

```bash
python scripts/run_eval.py                    # writes reports/eval_report.md
python scripts/run_eval.py --mode live        # same, with a live model
```

The report contains every case with its result and duration, any failures
with full tracebacks, the three example conversations, and the limitations
section. A machine-readable version is written to
`reports/eval_report.json`.

## 10. Layout

```
coverage_assistant/        the implementation package
  catalog.py               catalogue loading, inheritance, exclusion resolution
  state.py                 state normalization, authorization, referent resolution
  facts.py                 intent detection, fact pack construction
  prompts.py               system rules + fact pack assembly
  llm.py                   provider adapters, retries, spend caps
  guardrails.py            authorization scope, output validation
  offline_render.py        deterministic answer rendering (not an LLM)
  assistant.py             orchestration
  cli.py                   command-line entry point
starter/assistant.py       backwards-compatible shim for the supplied harness
data/                      supplied catalogue and scenarios (unchanged)
docs/                      root cause, architecture, conversations, runbook
reports/                   generated evaluation report
scripts/run_eval.py        evaluation runner
review_ui.py               local reviewer UI
tests/                     the evaluation suite
probe_*.py                 ad-hoc audit scripts used during development
                           (guardrail edge cases). They print findings; they
                           are not part of the automated suite.
```

## 11. Failure handling

| Failure | Behaviour |
| --- | --- |
| No API key in live mode | Explicit `MissingCredentialError` message; **no answer is invented** |
| Provider returns 4xx/5xx or times out | Bounded retries, then a `ProviderError` naming the cause; the answer says the model could not be reached |
| Malformed state | Normalized and ignored; the assistant answers with the plans that *are* authorized |
| Model output violates a guardrail | One repair attempt, then the deterministic fallback |
| Session call cap reached | `SpendCapError`; the assistant stops calling the provider |
| Catalog file missing or invalid | `CatalogError` with the path and the parse error |

In every case the assistant returns a string and never claims that a
template was written by a model.

## 12. Known limitations

* **Provider verification.** The live path was verified end to end against
  a local mock HTTP server (`tests/test_live_provider.py`, `tests/test_provider_modes.py`)
  and against a real local Ollama server running `qwen2.5:3b`
  (`http://localhost:11434/v1`). OpenAI was not called with a real API key
  in this environment; the OpenAI request shape is implemented and
  mock-tested but no live OpenAI round-trip was performed. This is flagged
  here rather than hidden, as the brief requires.
* **Offline mode cannot demonstrate model behaviour.** It demonstrates
  authorization, grounding and guardrails only.
* **Intent detection is keyword-based.** It is used to choose a response
  shape and to feed the validator, not to understand the question. An
  unrecognised question falls back to a general description of the plan in
  question.
* **The guardrails are conservative.** They can reject a correct answer
  (for example, an unusual phrasing of a valid deductible). This is a
  deliberate trade: a false refusal is recoverable, an unauthorized
  disclosure is not.
* **The catalogue is synthetic.** Nothing here authorises a real claim
  decision, and the `data/plans.json` disclaimer applies.
* **Out of scope**, per the brief: no web app, database, VIN decoder,
  checkout, authentication or deployment.

### Provider trade-offs

No claim is made that one provider is more accurate or faster than another;
no measurements support such a claim.

| Provider | Advantages | Considerations |
| --- | --- | --- |
| **OpenAI** | Managed API, straightforward reviewer testing with a personal key | Per-request API charges; depends on network and provider availability |
| **Local Llama via Ollama** | No per-request API charges; supports offline/local development | Consumes local compute resources; quality and latency depend on the installed model and hardware |
| **Offline deterministic** | Predictable baseline behaviour; credential-free; useful for testing | Not equivalent to a live LLM; cannot demonstrate model behaviour |

## 13. Delivery

| | |
| --- | --- |
| Repository | `https://github.com/Shivani767/360Covered_AI_Challenge_Candidate` (private) |
| Collaborator | `darkside720` (invitation sent and pending acceptance) |
| Branch | `master` |
| Runtime dependencies | none (Python standard library only) |
| Python version | 3.9 or newer |

To accept the invitation, `darkside720` should open
<https://github.com/Shivani767/360Covered_AI_Challenge_Candidate/invitations>
and accept, then clone with their own GitHub credentials:

```bash
git clone https://github.com/Shivani767/360Covered_AI_Challenge_Candidate.git
cd 360Covered_AI_Challenge_Candidate
python3 -m unittest discover -s tests -v
python3 scripts/run_eval.py
python3 review_ui.py     # http://127.0.0.1:8765
```

### Environment prerequisites

| Requirement | Needed for | Notes |
| --- | --- | --- |
| Python 3.9+ | Everything | Standard library only; no `pip install` step |
| A modern browser | The reviewer UI | The UI is a local HTTP server on `127.0.0.1` |
| Ollama + a pulled model | Live mode via a local LLM | Optional. Verified live with `qwen2.5:3b` |
| An OpenAI API key | Live mode via OpenAI | Optional. The request shape is implemented and mock-tested; **no live OpenAI round-trip was performed** |
| An Anthropic API key | Live mode via Anthropic | Optional. Same caveat as OpenAI |

Nothing above is required to run the tests, the evaluation report, the CLI
or the reviewer UI in offline mode.
