---
id: lo-c48f
title: "T20: Calibrate ranking against blind manual ranking of 20 held-out ads"
priority: 5
deps: [lo-b422, lo-b313]
requires: [surface:human]
workspace: MATCH
tags: [human, m3]
---

## Acceptance gate

```gate
rank_spearman >= 0.60
evidence: status/evidence/T20.json
key: rank_spearman
```

```bash
echo "no gate command defined for T20 — replace this line with the command that writes status/evidence/T20.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T20.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_ranking_correlates_with_manual_order` in `tests/test_calibration.py` — Spearman ρ ≥ 0.60 against the recorded manual order

## Location

Service: **MATCH** · Size: M

Design: `status/plan.md` (T20) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`

## Human-owned

Requires the candidate personally. Carries `requires: [surface:human]`, a
capability no surface declares, so the selector excludes it by default — the
`human` tag alone would not, since tags only filter when LOOP_TAGS is set.
