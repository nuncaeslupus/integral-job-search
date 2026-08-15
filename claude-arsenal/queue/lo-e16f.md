# T4: Corpus harness: ad store, labelling CLI, split assignment, self-agreement report

## Acceptance gate

```gate
corpus_harness_roundtrip_loss == 0
evidence: status/evidence/T4.json
key: corpus_harness_roundtrip_loss
```

Write the measured value to `status/evidence/T4.json` as `{"corpus_harness_roundtrip_loss": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_corpus_roundtrip_preserves_text_and_offsets` in `tests/test_corpus.py` — writing then reading an ad preserves text byte-for-byte and label offsets

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T4) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
