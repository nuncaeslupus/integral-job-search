# T4: Corpus harness: ad store, labelling CLI, split assignment, self-agreement report

## Acceptance gate

```gate
corpus_harness_roundtrip_loss == 0
evidence: status/evidence/T4.json
key: corpus_harness_roundtrip_loss
```

```bash
echo "no gate command defined for T4 — replace this line with the command that writes status/evidence/T4.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T4.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_corpus_roundtrip_preserves_text_and_offsets` in `tests/test_corpus.py` — writing then reading an ad preserves text byte-for-byte and label offsets

## Location

Service: **ONTOLOGY** · Size: M

Design: `status/plan.md` (T4) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
