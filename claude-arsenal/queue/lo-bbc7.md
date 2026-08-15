# T18: Pareto frontier + salary-equivalent ordering + facet lists

## Acceptance gate

```gate
pareto_dominance_violations == 0
evidence: status/evidence/T18.json
key: pareto_dominance_violations
```

```bash
echo "no gate command defined for T18 — replace this line with the command that writes status/evidence/T18.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T18.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_dominated_offer_never_appears_in_frontier` in `tests/test_rank.py` — an offer worse on every dimension is excluded; `test_unknown_dimension_is_not_treated_as_neutral` — an unknown score does not count as average

## Location

Service: **MATCH** · Size: L

Design: `status/plan.md` (T18) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
