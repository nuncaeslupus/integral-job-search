---
id: t-7bf38efa
title: "T61: The \u00a71 amendment: the dimensions are what make an iterative search steerable"
priority: 10
deps: [t-b5cf7968]
workspace: ONTOLOGY
---

## Acceptance gate

```gate
spec_consistency_violations == 0
evidence: status/evidence/T61.json
key: spec_consistency_violations
```

```bash
# e.g. bash tests/surface_probe_test.sh
false  # fail until a real check replaces this
```

The `gate` block is settled by the design and is read from the default branch —
it is the assertion, and is not this task's to weaken. The `bash` block is the
shipped placeholder and **is** this task's to replace: it must regenerate
`status/evidence/T61.json`. A task whose measurement is undefined has not passed
its gate; it has not been measured.

## Tests

Write these RED before any production code:

`test_every_document_states_the_same_differentiator` in `tests/test_spec_consistency.py` — D-3's three documents agree after the amendment

`test_the_amendment_adds_a_sentence_without_removing_the_mechanism` — the dimension-model claim survives verbatim

## Design

`status/specs/iterative-sourcing.md` §1 · `status/plan.md` row T61.

Part of **iterative sourcing** — sourcing sits outside the 6 → 9 → 10 loop, so the
offer set is fixed by the least-informed moment in the process. The first blind
sitting measured the cost: of twenty adverts, one was worth applying to.
