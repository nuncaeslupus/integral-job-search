# T5: **[HUMAN]** Label the collected ads against the dimension model; assign elicitation/evaluation split

## Acceptance gate

`corpus_size >= 100` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_corpus_meets_size_and_language_mix` in `tests/test_corpus_content.py` — corpus has ≥100 labelled ads and the language mix is within ±10% of target

## Location

Service: **ONTOLOGY** · Size: L

Design: `status/plan.md` (T5) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`

## Human-owned

This task requires the candidate personally and cannot be completed by an
agent worker. Tagged `human`. Do not claim it.
