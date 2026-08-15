# T17: `ontology_hit_rate` reporting and staleness signal

## Acceptance gate

```gate
ontology_hit_rate >= 0.85
evidence: status/evidence/T17.json
key: ontology_hit_rate
```

```bash
echo "no gate command defined for T17 — replace this line with the command that writes status/evidence/T17.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T17.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_unmapped_concepts_are_counted_not_discarded` in `tests/test_ontology_health.py` — concepts outside the model appear in `unmapped_concepts` and lower the hit rate

## Location

Service: **MATCH** · Size: S

Design: `status/plan.md` (T17) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
