# T4b: Collect ≥100 raw ads (≈60 ES, 25 EN, 15 CA) for remote programming roles — text + source URL only, no labels

## Acceptance gate

`raw_ad_count >= 100` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_raw_corpus_meets_size_and_language_mix` in `tests/test_corpus_raw.py` — ≥100 raw ads and language mix within ±10% of target

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T4b) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
