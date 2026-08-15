# T7: Question bank generation from the dimension model

## Acceptance gate

`question_dimension_coverage == 1.0` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_every_generated_question_maps_to_a_dimension` in `tests/test_question_bank.py` — each generated question carries ≥1 resolvable dimension ID

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T7) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
