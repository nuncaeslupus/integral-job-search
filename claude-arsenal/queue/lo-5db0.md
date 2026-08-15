# T17: `ontology_hit_rate` reporting and staleness signal

## Acceptance gate

```gate
ontology_hit_rate >= 0.85
evidence: status/evidence/T17.json
key: ontology_hit_rate
```

Write the measured value to `status/evidence/T17.json` as `{"ontology_hit_rate": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_unmapped_concepts_are_counted_not_discarded` in `tests/test_ontology_health.py` — concepts outside the model appear in `unmapped_concepts` and lower the hit rate

## Location

Service: **MATCH** · Size: S

Design: `status/plan.md` (T17) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
