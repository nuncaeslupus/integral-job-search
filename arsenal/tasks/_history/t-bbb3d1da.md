---
id: t-bbb3d1da
title: "T62: Exhaustion as a measurement: a cycle that keeps finding the same jobs"
priority: 5
deps: [t-b5cf7968]
workspace: SUPPLY
status: merged
---

## Acceptance gate

```gate
exhaustion_triggers_without_a_reason == 0
evidence: status/evidence/T62.json
key: exhaustion_triggers_without_a_reason
```

```bash
uv run python -m integral.sourcing_strategy && uv run pytest tests/test_sourcing_strategy.py -q
```

The `gate` block is settled by the design and is read from the default branch —
it is the assertion, and is not this task's to weaken. The `bash` block is the
shipped placeholder and **is** this task's to replace: it must regenerate
`status/evidence/T62.json`. A task whose measurement is undefined has not passed
its gate; it has not been measured.

## Tests

Write these RED before any production code:

`test_a_cycle_repeating_known_offers_is_exhausted` in `tests/test_sourcing_strategy.py` — repeat share above `EXHAUSTION_REPEAT_SHARE` sets `exhausted`

`test_a_cycle_that_returned_nothing_is_exhausted_for_its_own_reason` — zero offers must not read as zero repeats

`test_no_exhaustion_is_recorded_without_a_reason` — an empty reason is a violation, not a trigger

## Design

`status/specs/iterative-sourcing.md` §5.2 · `status/plan.md` row T62.

Part of **iterative sourcing** — sourcing sits outside the 6 → 9 → 10 loop, so the
offer set is fixed by the least-informed moment in the process. The first blind
sitting measured the cost: of twenty adverts, one was worth applying to.
