---
id: t-a49db8df
title: "T127: a connector's probe can repeat its fixture, so the rot check compares a page with itself"
priority: 5
status: merged
---

Imported from issue #343 (parts 1 and 2; part 3, the CI path guard, is blocked
on the repository being public and stays open).

## Acceptance gate

```gate
connectors_whose_probe_repeats_its_fixture == 0
evidence: status/evidence/T127.json
key: connectors_whose_probe_repeats_its_fixture
```

```bash
uv run --extra dev pytest tests/test_probe_divergence.py tests/test_connector_exchange.py -q
uv run python -m integral.connector_health
```
