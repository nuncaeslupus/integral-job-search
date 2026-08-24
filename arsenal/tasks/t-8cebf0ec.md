---
id: t-8cebf0ec
title: "T65: Consent: a narrowing is licensed by a recorded decision, and a refusal is evidence"
priority: 5
deps: [t-16a59a39]
workspace: SUPPLY
---

## Acceptance gate

```gate
narrowings_without_a_recorded_decision == 0
evidence: status/evidence/T65.json
key: narrowings_without_a_recorded_decision
```

```bash
# e.g. bash tests/surface_probe_test.sh
false  # fail until a real check replaces this
```

The `gate` block is settled by the design and is read from the default branch —
it is the assertion, and is not this task's to weaken. The `bash` block is the
shipped placeholder and **is** this task's to replace: it must regenerate
`status/evidence/T65.json`. A task whose measurement is undefined has not passed
its gate; it has not been measured.

## Tests

Write these RED before any production code:

`test_a_narrowing_without_a_recorded_decision_is_refused` in `tests/test_sourcing_strategy.py` — the scope change cannot apply without the evidence row

`test_a_refusal_is_recorded_as_evidence_not_as_a_veto`

`test_a_refused_proposal_is_not_reasked_on_the_next_cycle` — same facet and direction, same trigger, no intervening evidence

## Design

`status/specs/iterative-sourcing.md` §5.5 · `status/plan.md` row T65.

Part of **iterative sourcing** — sourcing sits outside the 6 → 9 → 10 loop, so the
offer set is fixed by the least-informed moment in the process. The first blind
sitting measured the cost: of twenty adverts, one was worth applying to.
