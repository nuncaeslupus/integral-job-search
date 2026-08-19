---
id: lo-4ca5
title: "D-4: the Traits gate is assigned to T28 by the specification and to T27 by the work"
priority: 10
tags: [m3]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/24
---

## Acceptance gate

```gate
trait_gate_owner_contradictions == 0
evidence: status/evidence/D-4.json
key: trait_gate_owner_contradictions
```

```bash
echo "no gate command defined for D-4 — replace this line with the command that writes status/evidence/D-4.json" >&2; exit 1
```

## What the specification requires

`status/spec-v2-process.md` §9 assigns step 4's gate metric,
`trait_evidence_sufficiency`, to **T28**:

> `trait_evidence_sufficiency` | 4 Traits | T28 — every trait carries either a
> score with ≥2 independent episodes, or `insufficient`

`status/spec-v2-steps.md` step 4 repeats it: *Owner: T28.*

## What the work says

T28 is **continuous profile capture** — every candidate-facing surface appends
evidence. Its own gate is `profile_capture_coverage == 1.0`. It writes evidence
rows; it does not score traits.

The two-episode/two-occasion floor, the `insufficient` value, and the decision
to look for one more episode rather than refuse are all specified in **T27**,
the onboarding interview protocol. T27's own gate is
`interview_profile_coverage >= 0.90`.

So neither task's acceptance gate *is* the step metric, and the task that does
the scoring is not the one the specification names.

## The fix location

One of three, and it is the owner's call:

1. **Reassign to T27** in `status/spec-v2-process.md` §9,
   `status/spec-v2-steps.md` step 4 and `status/spec-v2-steps.json` — the
   scoring is T27's work.
2. **Keep T28** and move the trait floor into it, leaving T27 the conversation
   and T28 the scoring.
3. **Neither** — seed a third task that owns scoring alone, if the split is
   really capture / score / converse.

Whichever is chosen, a step gate must be some task's *measured* gate, not only
an attribution in a table. `status/plan.md` records the specification's answer
(T28) and points here rather than silently contradicting it, which is what a
plan is not allowed to do.

## Tests

`test_step_gate_metric_is_some_task_gate` in `tests/test_step_gates.py` — every
step's gate metric appears as the acceptance gate of at least one task;
`test_no_two_documents_name_different_owners_for_one_step_gate`.

## Location

Service: **ONTOLOGY** · Size: S · Depends: —

Design: `status/plan.md` (Step gate ownership) · Spec: `status/spec-v2-process.md` §9
