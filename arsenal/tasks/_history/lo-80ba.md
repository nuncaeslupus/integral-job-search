---
id: lo-80ba
title: "T7: Question bank generation from the dimension model"
priority: 5
deps: [lo-2774, lo-e0fa]
workspace: PROFILE
tags: [m3]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/24
---

## Acceptance gate

```gate
question_dimension_coverage == 1.0
evidence: status/evidence/T7.json
key: question_dimension_coverage
```

```bash
uv run python -m jobsearch.question_bank
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T7.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_every_generated_question_maps_to_a_dimension` in `tests/test_question_bank.py` — each generated question carries ≥1 resolvable dimension ID

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T7) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
