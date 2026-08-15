# T2: Dimension schema (Pydantic) + loader + validator, incl. `methods_ref` anchor resolution

## Acceptance gate

```gate
dimension_schema_violations == 0
evidence: status/evidence/T2.json
key: dimension_schema_violations
```

Write the measured value to `status/evidence/T2.json` as `{"dimension_schema_violations": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_dimension_missing_methods_ref_is_rejected` in `tests/test_dimension_model.py` — a dimension without `methods_ref` fails validation; `test_dimension_duplicate_id_is_rejected` — two files sharing an `id` fail to load

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T2) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
