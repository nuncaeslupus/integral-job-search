# T16: Negation handling in extraction

## Acceptance gate

```gate
extraction_negation_recall >= 0.80
evidence: status/evidence/T16.json
key: extraction_negation_recall
```

Write the measured value to `status/evidence/T16.json` as `{"extraction_negation_recall": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_negated_cue_inverts_not_drops_score` in `tests/test_negation.py` — "no on-call" yields a negative score, not a missing one

## Location

Service: **MATCH** · Size: M

Design: `status/plan.md` (T16) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
