# T17: `ontology_hit_rate` reporting and staleness signal

## Acceptance gate

`ontology_hit_rate >= 0.85` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_unmapped_concepts_are_counted_not_discarded` in `tests/test_ontology_health.py` — concepts outside the model appear in `unmapped_concepts` and lower the hit rate

## Location

Service: **MATCH** · Size: S

Design: `status/plan.md` (T17) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
