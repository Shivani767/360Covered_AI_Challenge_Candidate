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

## 2. The three reviewer modes

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
python -m unittest discover -s tests -v   # 127 cases, all offline
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
plan references, dollar amounts that do not match the catalogue, coverage
claims for options that were offered but not purchased, and coverage claims
for a part the plan in question explicitly excludes (for example, claiming
that DriveWrap covers the engine). A failing
answer gets one repair attempt with the specific violations listed, and
then a deterministic catalogue-derived fallback. The model never has the
last word.

## 6. Test suite

```bash
python -m unittest discover -s tests -v
```

127 cases, all offline and all passing on a clean machine:

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
| `tests/test_sweep.py` | Property-style sweep over many questions x many states |

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

## 11. Delivery

| | |
| --- | --- |
| Repository | `https://github.com/Shivani767/360Covered_AI_Challenge_Candidate` (private) |
| Collaborator | `darkside720` (push permission, invitation pending acceptance) |
| Branch | `master` |
| Runtime dependencies | none (Python standard library only) |
| Python version | 3.9 or newer |

To accept the invitation, `darkside720` should open
<https://github.com/Shivani767/360Covered_AI_Challenge_Candidate/invitations>
and accept, then clone with their own GitHub credentials.
