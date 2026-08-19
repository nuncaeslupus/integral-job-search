---
id: lo-d92d
title: "D-7: spec-v2-steps.md names two owners for the Ranking gate; the JSON names one"
priority: 10
workspace: SOLO
tags: [m2]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/24
---

Found while writing S7's thirteen step skills, which have to name each step's
gate metric and therefore had to pick one.

## What the spec requires

One step, one gate metric, one owning task. `step_gates.py` derives each step's
implemented/not_implemented state by reading the evidence file belonging to
`gate.task`, so a step with two owners has no single file to read and the
register cannot be truthful about it.

## What the documents do

- `status/spec-v2-steps.md`, step 9 (Ranking): names **two** owners, T18 and T19.
- `status/spec-v2-steps.json`, `ranking.gate.task`: names **one**, `"T19"`.

S7 used the JSON's single value, because that is the field `step_gates.py`
actually reads — but the prose a human reads says something else. This is the
same class of contradiction as D-4 (the Traits gate assigned to T28 by the
specification and T27 by the work), and it should be resolved the same way:
decide which task owns the *metric*, and say so once.

Note the likely answer is not "delete T18". T18 and T19 are both real work —
T18 ranks, T19 explains — exactly as T24 pins the constraint fields while T41
resolves them. That split is fine; what is not fine is two documents disagreeing
about which of them the gate is read from.

A related instance was already corrected in passing on PR #23: the constraints
step's `gate.task` named T24 while `constraint_field_resolution` is measured and
written by T41, so the register read the step as not implemented while it was
passing at 1.0. Check whether any other step carries the same mismatch — the
check below is the general form of it.

## Acceptance gate

Every step's `gate.task` names exactly one task, that task's evidence file is
the one carrying the step's gate metric, and no prose document names a
different owner for the same gate.

```bash
uv run pytest tests/test_step_specs.py tests/test_step_gates.py -q
uv run python -m jobsearch.step_gates
```

```gate
step_gate_owner_contradictions == 0
evidence: status/evidence/D7.json
key: step_gate_owner_contradictions
```

## Tests

`test_every_step_gate_names_exactly_one_owner`;
`test_the_gate_task_is_the_task_that_writes_the_metric` — the mismatch that made
the constraints step read as not implemented, generalised to all thirteen;
`test_no_prose_document_names_a_different_owner_than_the_json`.

## Location

`status/spec-v2-steps.md`, `status/spec-v2-steps.json`,
`src/jobsearch/step_gates.py`, `tests/test_step_specs.py`
