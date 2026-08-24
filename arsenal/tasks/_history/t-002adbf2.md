---
id: t-002adbf2
title: "T63: Step 7 becomes offerable again on exhaustion \u2014 a new trigger kind beside staleness"
priority: 5
deps: [t-bbb3d1da]
workspace: RUNTIME
status: merged
---

## Acceptance gate

```gate
stuck_cycles_without_a_proposal == 0
evidence: status/evidence/T63.json
key: stuck_cycles_without_a_proposal
```

```bash
uv run python -m integral.sourcing_reentry && uv run pytest tests/test_freshness.py -q
```

The `gate` block is settled by the design and is read from the default branch —
it is the assertion, and is not this task's to weaken. The `bash` block is the
shipped placeholder and **is** this task's to replace: it must regenerate
`status/evidence/T63.json`. A task whose measurement is undefined has not passed
its gate; it has not been measured.

## Tests

Write these RED before any production code:

`test_an_exhausted_step_seven_is_offered_again` in `tests/test_freshness.py` — a finished sourcing step re-enters on an `exhausted` trigger

`test_staleness_behaviour_is_unchanged_by_the_new_kind` — the existing trigger fires exactly as before

`test_an_exhausted_cycle_never_reruns_the_same_search_silently` — re-entry carries a proposal

## Design

`status/specs/iterative-sourcing.md` §5.3 · `status/plan.md` row T63.

Part of **iterative sourcing** — sourcing sits outside the 6 → 9 → 10 loop, so the
offer set is fixed by the least-informed moment in the process. The first blind
sitting measured the cost: of twenty adverts, one was worth applying to.
