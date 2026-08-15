# T10: Preference weights: forced pairwise choices → part-worths → salary-equivalent scale

## Acceptance gate

`weight_salary_equivalent_roundtrip_error <= 0.01` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_partworth_to_salary_equivalent_roundtrips` in `tests/test_weights.py` — converting a dimension to €/month and back recovers the part-worth within 1%

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T10) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
