# T18: Pareto frontier + salary-equivalent ordering + facet lists

## Acceptance gate

```gate
pareto_dominance_violations == 0
evidence: status/evidence/T18.json
key: pareto_dominance_violations
```

Write the measured value to `status/evidence/T18.json` as `{"pareto_dominance_violations": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_dominated_offer_never_appears_in_frontier` in `tests/test_rank.py` — an offer worse on every dimension is excluded; `test_unknown_dimension_is_not_treated_as_neutral` — an unknown score does not count as average

## Location

Service: **MATCH** · Size: L

Design: `status/plan.md` (T18) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
