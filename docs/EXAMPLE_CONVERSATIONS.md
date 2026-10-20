# Example conversations

Three worked conversations. They are reproduced from the deterministic
offline adapter so they are exactly what a reviewer will see when running
the project without credentials. In live mode the wording differs, but the
safety properties asserted here are enforced by code and are checked by the
test suite either way.

Reproduce conversation C1 with:

```bash
python -m coverage_assistant.cli -q "Just give me the plan that covers everything." \
  --state '{"eligible_ids":["P-BASE","P-PLUS","P-EXCL"],"visible_ids":["P-BASE","P-PLUS"],"selected_id":"P-PLUS","selected_options":[]}'
```

---

## C1 - "Just give me the plan that covers everything"

This is the request the brief singles out. The customer asks for a
universal plan.

**State**

```json
{
  "eligible_ids": ["P-BASE", "P-PLUS", "P-EXCL"],
  "visible_ids": ["P-BASE", "P-PLUS"],
  "selected_id": "P-PLUS",
  "selected_options": []
}
```

`P-EXCL` is eligible but **not visible**. The starter would have offered
it and promised it covered everything.

**Customer:** Just give me the plan that covers everything.

**Assistant:**

> No. I am not able to describe any plan here as covering everything. Every
> plan in the catalogue carries exclusions, so there is no blanket promise to
> be made. Exclusions that apply to the plans you can see include:
> pre-existing failures, normal maintenance items, damage caused by continued
> operation after malfunction. CoreDrive Plus covers: factory
> air-conditioning compressor, alternator, starter motor, factory-installed
> radiator, front suspension control arms, engine internal lubricated parts,
> transmission internal lubricated parts, drive axle internal parts.
> Optional coverage: you have not purchased any optional coverage. The
> optional items available on your plan are electronics_plus, exhaust_plus -
> they are offered, not in force, until purchased. Please note: repairs
> normally require prior authorization; maintenance documentation may be
> requested; final claims decision is made by the administrator.

**What makes this safe**

* The universal request is refused, with the reason (exclusions exist).
* `P-EXCL` is never named: the customer did not name it, so it does not
  enter the fact pack at all.
* No price, deductible or component list of `P-EXCL` appears.
* The offered-but-not-purchased options are labelled as such.
* The administrator's claims conditions are quoted from the catalogue.

**Code path**

`detect_intent` flags `universal_cover` -> `offline_render.render_answer`
takes the universal branch -> the universal-promise detector in
`facts.detect_universal_claim` is negation-aware, so the refusal itself is
not flagged as a promise.

---

## C2 - "Is my navigation screen covered?"

The customer asks about a part covered by an option they have **not**
purchased. The distinction between *offered* and *purchased* is the whole
point of this case.

**State**

```json
{
  "eligible_ids": ["P-PLUS"],
  "visible_ids": ["P-PLUS"],
  "selected_id": "P-PLUS",
  "selected_options": []
}
```

**Customer:** Is my navigation screen covered?

**Assistant:**

> factory-installed navigation screen would be covered by the
> electronics_plus option. That option is offered on your plan but has not
> been purchased, so factory-installed navigation screen is not currently
> covered. Optional coverage: you have not purchased any optional coverage.
> The optional items available on your plan are electronics_plus,
> exhaust_plus - they are offered, not in force, until purchased.

**Now purchase the option**

Change `selected_options` to `["electronics_plus"]` and ask again:

**Customer:** Is my navigation screen covered?

**Assistant:**

> factory-installed navigation screen is covered by your electronics_plus
> option, which you have purchased. Optional coverage: you have purchased
> electronics_plus. These are the optional items on your plan:
> electronics_plus, exhaust_plus.

**What makes this safe**

* The answer distinguishes **offered** from **purchased** using two
  separate fact-pack fields, not inference.
* The guardrail rejects "your navigation screen is covered" when the option
  is not purchased, but accepts "would be covered by electronics_plus,
  which you have not purchased". The check is sentence-scoped and
  negation-aware.
* `option_status[].covers_mentioned_components` links the customer's
  wording ("navigation screen") to the catalogue wording ("factory-installed
  navigation screen") through the alias table in `facts.COMPONENT_ALIASES`.

---

## C3 - Plan switch mid-conversation

The customer asks about one plan, changes their selection, then uses a
pronoun. The answer must follow the **current** selection.

**State (turn 1)**

```json
{
  "eligible_ids": ["P-BASE", "P-PLUS"],
  "visible_ids": ["P-BASE", "P-PLUS"],
  "selected_id": "P-BASE",
  "selected_options": []
}
```

**Customer:** Tell me about CoreDrive

**Assistant:**

> CoreDrive covers: engine internal lubricated parts, transmission internal
> lubricated parts, drive axle internal parts. CoreDrive (P-BASE) is $89 per
> month with a $200 deductible.

**State changes:** `selected_id` becomes `P-PLUS`.

**Customer:** What is its deductible?

**Assistant:**

> The deductible for CoreDrive Plus (P-PLUS) is $100. Optional coverage: you
> have not purchased any optional coverage. The optional items available on
> your plan are electronics_plus, exhaust_plus - they are offered, not in
> force, until purchased.

**What makes this safe**

* The referent resolves to the **current** selection, not to the plan
  discussed in the previous turn. The starter's `self.last_plan_id` was
  consulted *before* `selected_id` and would have answered "$200".
* The answer is checked against the referent's catalogue deductible: the
  guardrail fails the answer if it states a deductible that is not the
  catalogue value for the plan in question.
* A plan that becomes invisible disappears from the next answer entirely
  (see `tests/test_multiturn.py::test_plan_is_not_sticky_after_visibility_change`).

---

## Bonus: the Wrap plan

**State:** `eligible_ids: ["P-BASE", "P-WRAP"]`, `visible_ids: ["P-BASE",
"P-WRAP"]`, `selected_id: "P-WRAP"`.

**Customer:** Does DriveWrap cover my engine?

**Assistant:**

> engine internal lubricated parts is not covered by DriveWrap; it is
> explicitly excluded. Note: DriveWrap requires active outside powertrain
> warranty.

`P-WRAP` has no `inherits` key, so it inherits nothing from `P-BASE`, and
its `explicitly_excludes` list names the powertrain internals. The starter
would have let the model read `P-WRAP`'s component list, which looks
similar to `P-PLUS`'s, and infer engine coverage.
