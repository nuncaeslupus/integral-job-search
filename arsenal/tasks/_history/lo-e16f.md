---
id: lo-e16f
title: "T4: Corpus harness: ad store, labelling CLI, split assignment, self-agreement report"
priority: 90
deps: [lo-3f5e]
workspace: ONTOLOGY
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/9
---

## Acceptance gate

```gate
corpus_harness_roundtrip_loss == 0
evidence: status/evidence/T4.json
key: corpus_harness_roundtrip_loss
```

```bash
uv run python -m jobsearch.harness gate --evidence status/evidence/T4.json
uv run --extra dev pytest tests/test_corpus.py -q
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T4.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The committed store is unlabelled until T5, so a roundtrip over it alone would
preserve offsets vacuously — having none to preserve. `gate` therefore measures
twice: once over the store as committed, and once over a copy carrying a probe
label per ad whose offsets come from a real cue match in real ad text. Both must
come back with zero loss.

## Tests

Write these RED before any production code:

`test_corpus_roundtrip_preserves_text_and_offsets` in `tests/test_corpus.py` — writing then reading an ad preserves text byte-for-byte and label offsets

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T4) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
