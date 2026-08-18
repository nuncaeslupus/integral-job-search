# T48: Step gate state register — derive each step's state from recorded evidence

## Acceptance gate

```gate
step_gate_state_drift == 0
evidence: status/evidence/T48.json
key: step_gate_state_drift
```

```bash
uv run --extra dev pytest tests/test_step_gates.py -q
uv run --extra dev python -m jobsearch.step_gates status/evidence/T48.json
```

## What this is

Every step in `spec-v2-steps.json` carries a gate metric and a `state`. All
thirteen currently read `not_implemented`, which is truthful today and will stop
being truthful the moment a gate first passes — because the field is hand-edited
and nothing checks it.

This derives it: a step's state is computed from `status/evidence/*.json`, and
the hand-edited value becomes a value that is checked rather than declared.

## The rule that matters

**A gate metric must be counted, never restated.** The S2 checker learned this
the hard way — `steps_with_named_gate_metric` divided by `step_count` instead of
counting, so the field meant to say *which* step lacked a metric would have said
all of them had one. The same failure mode applies here: a state register that
trusts its own input reports whatever it was told.

`not_implemented` is a recorded value, not a blank, and remains valid for a step
with no evidence file yet.

## Tests

Write these RED before any production code:

`test_step_state_matches_recorded_evidence` in `tests/test_step_gates.py` — a
step whose evidence file records a passing measurement cannot read
`not_implemented`; `test_missing_evidence_reads_not_implemented`;
`test_failing_evidence_does_not_read_implemented`.

## Location

Service: **ONTOLOGY** · Size: S · Depends: T30

Design: `status/plan.md` (ONTOLOGY) · Spec: `status/spec-v2-process.md` §9
