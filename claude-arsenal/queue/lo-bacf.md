# T10: Preference weights: forced pairwise choices → part-worths → salary-equivalent scale

## Acceptance gate

```gate
weight_salary_equivalent_roundtrip_error <= 0.01
evidence: status/evidence/T10.json
key: weight_salary_equivalent_roundtrip_error
```

Write the measured value to `status/evidence/T10.json` as `{"weight_salary_equivalent_roundtrip_error": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_partworth_to_salary_equivalent_roundtrips` in `tests/test_weights.py` — converting a dimension to €/month and back recovers the part-worth within 1%

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T10) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
