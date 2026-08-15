# T20: **[HUMAN]** Calibrate ranking against blind manual ranking of 20 held-out ads

## Acceptance gate

```gate
rank_spearman >= 0.60
evidence: status/evidence/T20.json
key: rank_spearman
```

Write the measured value to `status/evidence/T20.json` as `{"rank_spearman": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

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
