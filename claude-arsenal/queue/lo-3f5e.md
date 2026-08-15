# T2: Dimension schema (Pydantic) + loader + validator, incl. `methods_ref` anchor resolution

## Acceptance gate

```gate
dimension_schema_violations == 0
evidence: status/evidence/T2.json
key: dimension_schema_violations
```

```bash
echo "no gate command defined for T2 — replace this line with the command that writes status/evidence/T2.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T2.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_dimension_missing_methods_ref_is_rejected` in `tests/test_dimension_model.py` — a dimension without `methods_ref` fails validation; `test_dimension_duplicate_id_is_rejected` — two files sharing an `id` fail to load

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T2) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
