---
id: t-4efbff9b
title: "T66: The empty market: report a time, never a relaxed constraint"
priority: 5
deps: [t-16a59a39, t-8cebf0ec]
workspace: SUPPLY
status: merged
---

## Acceptance gate

```gate
exhausted_searches_reported_as_a_scope_change == 0
evidence: status/evidence/T66.json
key: exhausted_searches_reported_as_a_scope_change
```

```bash
uv run python -m integral.sourcing_market && uv run pytest tests/test_sourcing_strategy.py -q
```

The `gate` block is settled by the design and is read from the default branch —
it is the assertion, and is not this task's to weaken. The `bash` block is the
shipped placeholder and **is** this task's to replace: it must regenerate
`status/evidence/T66.json`. A task whose measurement is undefined has not passed
its gate; it has not been measured.

## Tests

Write these RED before any production code:

`test_an_empty_market_is_reported_as_a_time_not_a_compromise` in `tests/test_sourcing_strategy.py` — the offer is to come back later, and names no constraint

`test_the_empty_market_needs_exhaustion_in_both_directions` — one stale cycle does not reach it

`test_no_hard_constraint_is_proposed_for_relaxation_on_an_empty_result`

## Design

`status/specs/iterative-sourcing.md` §5.6 · `status/plan.md` row T66.

Part of **iterative sourcing** — sourcing sits outside the 6 → 9 → 10 loop, so the
offer set is fixed by the least-informed moment in the process. The first blind
sitting measured the cost: of twenty adverts, one was worth applying to.
