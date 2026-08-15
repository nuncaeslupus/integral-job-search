# T18: Pareto frontier + salary-equivalent ordering + facet lists

## Acceptance gate

`pareto_dominance_violations == 0` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_dominated_offer_never_appears_in_frontier` in `tests/test_rank.py` — an offer worse on every dimension is excluded; `test_unknown_dimension_is_not_treated_as_neutral` — an unknown score does not count as average

## Location

Service: **MATCH** · Size: L

Design: `status/plan.md` (T18) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
