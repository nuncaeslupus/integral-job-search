# T12: One live portal connector against recorded fixtures

## Acceptance gate

`connector_fixture_parse_f1 >= 0.95` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_connector_parses_fixture_pages_to_offers` in `tests/test_connect_portal.py` — recorded pages parse to expected offers at F1 ≥ 0.95

## Location

Service: **SUPPLY** · Size: L

Design: `status/plan.md` (T12) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
