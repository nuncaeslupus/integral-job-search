# T15: LLM structured extraction: dimension scores, evidence spans, `unmapped_concepts`

## Acceptance gate

`extraction_macro_f1 >= 0.75` — measured and recorded in the plan's Evidence log.

```bash
make lint && make test  # replace with the check that measures the gate
```

## Tests

Write these RED before any production code:

`test_extraction_matches_corpus_labels` in `tests/test_extract.py` — macro-F1 ≥ 0.75 on the evaluation split; `test_score_without_evidence_span_is_rejected` — a score with an empty evidence list fails validation

## Location

Service: **MATCH** · Size: L

Design: `status/plan.md` (T15) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
