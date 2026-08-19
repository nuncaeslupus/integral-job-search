---
id: lo-3f5e
title: "T2: Dimension schema (Pydantic) + loader + validator, incl. `methods_ref` anchor resolution"
priority: 95
deps: [lo-0204]
workspace: ONTOLOGY
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/7
---

## Acceptance gate

```gate
dimension_schema_violations == 0
evidence: status/evidence/T2.json
key: dimension_schema_violations
```

```bash
uv run python -m jobsearch.dimensions status/evidence/T2.json
uv run --extra dev pytest tests/test_dimension_model.py -q
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T2.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The evidence writer exits non-zero when `dimensions/` is empty: zero violations
over zero files is a pass over nothing, which is the one way this gate could
have measured nothing while reporting success.

## Tests

Write these RED before any production code:

`test_dimension_missing_methods_ref_is_rejected` in `tests/test_dimension_model.py` — a dimension without `methods_ref` fails validation; `test_dimension_duplicate_id_is_rejected` — two files sharing an `id` fail to load

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T2) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
