# T13: Cross-source dedup + expiry detection

## Acceptance gate

`dedup_precision >= 0.95` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_crossposted_duplicates_are_collapsed` in `tests/test_dedup.py` — seeded duplicates collapse with precision ≥ 0.95; `test_distinct_roles_at_same_company_are_not_merged` — near-identical titles at one company stay separate

## Location

Service: **SUPPLY** · Size: M

Design: `status/plan.md` (T13) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
