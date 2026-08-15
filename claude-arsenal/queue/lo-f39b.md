# T9: Reaction elicitation: corpus stimuli, capture, extraction, disjoint-split enforcement

## Acceptance gate

`elicitation_eval_overlap == 0` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_elicitation_never_draws_from_evaluation_split` in `tests/test_reaction_elicit.py` — selecting stimuli from the evaluation split raises

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T9) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
