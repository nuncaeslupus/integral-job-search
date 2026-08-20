---
id: lo-f55b
title: "T41: Constraints step engine — confirm-and-fill from claims, ask from scratch without them"
priority: 5
deps: [lo-e0fa, lo-b876]
tags: [m2]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/23
---

## Acceptance gate

```gate
constraint_field_resolution == 1.0
evidence: status/evidence/T41.json
key: constraint_field_resolution
```

```bash
uv run --extra dev pytest tests/test_constraints_step.py -q
uv run --extra dev python -m jobsearch.constraints_step status/evidence/T41.json
```

## What this is

Constraints is required; Intake is offered. So this step has two openings and
must be good at both.

**With claims available** it opens by showing what Intake inferred and asks the
candidate to correct it in place — which is what makes this step short. **With
no claims** it asks from scratch, which makes it longer and not harder.

Every field ends as exactly one of `stated`, `declined` or `unknown`. T24 pins
the field set and the states; this task resolves them in conversation and writes
`profile/constraints.json`, derived.

## The rule that matters

**A claim is not a fact.** "Barcelona" extracted from a CV header is a claim
the document makes, not an established residence. The step promotes claims to
confirmed facts by asking; anything the candidate does not confirm stays
`unknown`, which neither passes nor vetoes.

**This is the step where the required-only path breaks first**, and it broke
once already in the specification. A candidate with no CV must reach a resolved
constraint set without Intake having run.

## Tests

Write these RED before any production code:

`test_every_constraint_field_resolves_to_one_of_three_states` in
`tests/test_constraints_step.py`; `test_unconfirmed_claim_stays_unknown` — an
inferred claim never becomes a fact without confirmation;
`test_step_runs_with_no_claims_present` — the required-only path, with Intake
declined; `test_declined_is_distinct_from_unknown`.

## Location

Service: **PROFILE** · Size: M · Depends: T24, T6

Design: `status/plan.md` (PROFILE) · Spec: `status/spec-v2-steps.md` step 2
