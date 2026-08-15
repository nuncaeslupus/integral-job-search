# T5: **[HUMAN]** Label the collected ads against the dimension model; assign elicitation/evaluation split

## Acceptance gate

```gate
corpus_size >= 100
evidence: status/evidence/T5.json
key: corpus_size
```

```bash
echo "no gate command defined for T5 — replace this line with the command that writes status/evidence/T5.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T5.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

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
