# T19: Explanations citing verbatim evidence spans and €/month contributions

## Acceptance gate

`explained_fraction == 1.0` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_every_ranked_offer_cites_evidence` in `tests/test_explain.py` — each ranked offer carries ≥1 verbatim span per contributing dimension

## Location

Service: **MATCH** · Size: M

Design: `status/plan.md` (T19) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
