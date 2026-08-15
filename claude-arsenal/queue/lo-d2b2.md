# T5: **[HUMAN]** Label the collected ads against the dimension model; assign elicitation/evaluation split

## Acceptance gate

```gate
corpus_size >= 100
evidence: status/evidence/T5.json
key: corpus_size
```

Write the measured value to `status/evidence/T5.json` as `{"corpus_size": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_corpus_meets_size_and_language_mix` in `tests/test_corpus_content.py` — corpus has ≥100 labelled ads and the language mix is within ±10% of target

## Location

Service: **ONTOLOGY** · Size: L

Design: `status/plan.md` (T5) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`

## Human-owned

Requires the candidate personally. Carries `requires: [surface:human]`, a
capability no surface declares, so the selector excludes it by default — the
`human` tag alone would not, since tags only filter when LOOP_TAGS is set.
