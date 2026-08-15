# T7: Question bank generation from the dimension model

## Acceptance gate

```gate
question_dimension_coverage == 1.0
evidence: status/evidence/T7.json
key: question_dimension_coverage
```

Write the measured value to `status/evidence/T7.json` as `{"question_dimension_coverage": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_every_generated_question_maps_to_a_dimension` in `tests/test_question_bank.py` — each generated question carries ≥1 resolvable dimension ID

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T7) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
