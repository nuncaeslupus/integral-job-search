# T2: Dimension schema (Pydantic) + loader + validator, incl. `methods_ref` anchor resolution

## Acceptance gate

`dimension_schema_violations == 0` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_dimension_missing_methods_ref_is_rejected` in `tests/test_dimension_model.py` — a dimension without `methods_ref` fails validation; `test_dimension_duplicate_id_is_rejected` — two files sharing an `id` fail to load

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T2) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
