# T22: `methods_ref` link check across dimensions and computation sites

## Acceptance gate

`undocumented_methods == 0` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_every_methods_ref_resolves_to_an_anchor` in `tests/test_methods_links.py` — every `methods_ref` resolves to a heading in `docs/METHODS.md`

## Location

Service: **ONTOLOGY** · Size: S

Design: `status/plan.md` (T22) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
