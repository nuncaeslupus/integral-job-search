---
id: lo-bd02
title: "T16: Negation handling in extraction"
priority: 5
deps: [lo-25b1]
workspace: MATCH
tags: [m2]
---

## Acceptance gate

```gate
extraction_negation_recall >= 0.80
evidence: status/evidence/T16.json
key: extraction_negation_recall
```

```bash
echo "no gate command defined for T16 — replace this line with the command that writes status/evidence/T16.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T16.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_negated_cue_inverts_not_drops_score` in `tests/test_negation.py` — "no on-call" yields a negative score, not a missing one

## Location

Service: **MATCH** · Size: M

Design: `status/plan.md` (T16) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
