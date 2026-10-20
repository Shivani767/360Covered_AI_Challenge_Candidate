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
git clone <this-repo>
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

## 2. The two reviewer modes

The brief requires two modes, and they must not be confused with each other.

| Mode | Command | Model used | Credentials |
| --- | --- | --- | --- |
| **(a) Offline / deterministic** | `python review_ui.py` | **None.** A rule-based renderer | **None** |
| **(b) Live LLM** | `ASSISTANT_MODE=live python review_ui.py` | A real LLM API call | Reviewer's own key |

Every offline answer is prefixed with `OFFLINE_DETERMINISTIC - NOT AN LLM`,
and the UI shows a yellow **OFFLINE_DETERMINISTIC** badge. In live mode the
badge turns green and reads `LIVE LLM (openai: gpt-4o-mini)`. A canned
answer is never presented as if a model had produced it - this is asserted
in the test suite (`tests/test_adversarial.py`).

### (a) Offline mode - credential-free

```bash
python review_ui.py                       # open http://127.0.0.1:8765
python -m unittest discover -s tests -v   # 69 cases, all offline
```

The offline adapter is a deterministic renderer over the same fact pack the
model receives. It proves the authorization, grounding and guardrail
behaviour. **It is not a language model and earns no credit for live model
behaviour.** Its role in this submission is to act as a test oracle and as
the safe fallback when a live model's output fails validation.

### (b) Live mode - a real LLM call

Set **your own** key, then run with `ASSISTANT_MODE=live`:

```bash
# OpenAI
export OPENAI_API_KEY=sk-...
ASSISTANT_MODE=live python review_ui.py

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
ASSISTANT_MODE=live python review_ui.py

# Any OpenAI-compatible server (Ollama, vLLM, LM Studio, a gateway)
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_API_KEY=whatever-your-server-wants
ASSISTANT_MODE=live python review_ui.py
```

The same works from the command line:

```bash
ASSISTANT_MODE=live python -m coverage_assistant.cli \
  -q "What does DriveWrap cover?" --show-trace
```

If no key is set, live mode fails with an explicit message
(`No API key found. Set OPENAI_API_KEY ...`) and **no answer is fabricated**.
The UI shows the error rather than a plausible-looking reply.

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

## 3. What the reviewer can do in the UI

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

The UI is a standard-library HTTP server bound to `127.0.0.1` only. There
is no auth, no database and no external dependency.

## 4. What was fixed, and why

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

## 5. Safety model in one paragraph

The allowed plan set is computed in code as `eligible_ids ∩ visible_ids`.
Only those plans enter the fact pack, so the model cannot describe an
invisible plan. After generation, the answer is checked for universal
coverage promises, guarantee and claims-decision language, unauthorised
plan references, dollar amounts that do not match the catalogue, and
coverage claims for options that were offered but not purchased. A failing
answer gets one repair attempt with the specific violations listed, and
then a deterministic catalogue-derived fallback. The model never has the
last word.

## 6. Test suite

```bash
python -m unittest discover -s tests -v
```

69 cases, all offline and all passing on a clean machine:

| File | Covers |
| --- | --- |
| `tests/test_catalog.py` | Inheritance, the Wrap special case, exclusionary-style plans, prices, ordering |
| `tests/test_state.py` | Authorization intersection, malformed state, referent resolution, option matching |
| `tests/test_guardrails.py` | Each validation rule, driven with deliberately unsafe candidate answers |
| `tests/test_scenarios.py` | All six supplied scenarios from `data/scenarios.json` |
| `tests/test_adversarial.py` | Prompt injection, malformed state, provider failures |
| `tests/test_multiturn.py` | Selection changes, visibility changes, option purchase/removal, bounded history |
| `tests/test_live_provider.py` | The live HTTP path against a local mock server: real request, fact pack on the wire, unsafe answer caught, spend cap, error surfacing |
| `tests/test_smoke.py` | The supplied smoke test, unchanged |

`tests/test_live_provider.py` starts a local mock HTTP server on a random
port. It needs no key and no network, and it exercises the same code path
as a real provider.

## 7. Evaluation report

```bash
python scripts/run_eval.py                    # writes reports/eval_report.md
python scripts/run_eval.py --mode live        # same, with a live model
```

The report contains every case with its result and duration, any failures
with full tracebacks, the three example conversations, and the limitations
section. A machine-readable version is written to
`reports/eval_report.json`.

## 8. Layout

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
```

## 9. Failure handling

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

## 10. Known limitations

* **No real provider round-trip was performed.** The candidate environment
  had no API key. The live path was verified end to end against a local
  mock HTTP server that speaks the OpenAI chat-completions shape
  (`tests/test_live_provider.py`), and the Anthropic request shape is
  implemented but unverified against a live endpoint. This is flagged here
  rather than hidden, as the brief requires.
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

## 11. AI tools used

An AI coding assistant (Cline, running on an LLM) was used to write and
refactor this package, to draft the test suite, and to produce the
documentation. The design decisions, the guardrail rules, the catalogue
resolution logic and the verification steps are the candidate's own; every
behaviour asserted in the test suite was executed and checked locally.
