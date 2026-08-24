---
id: lo-c48f
title: "T20: Calibrate ranking against blind manual ranking of 20 held-out ads"
priority: 5
deps: [lo-b422, lo-b313, t-c2c4dddb]
requires: [surface:human]
workspace: MATCH
tags: [human, m3]
---

## Acceptance gate

```gate
rank_spearman >= 0.60
evidence: status/evidence/T20.json
key: rank_spearman
status-key: rank_status
```

```bash
uv run python -m integral.calibration spearman status/evidence/T20.json
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T20.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

T20a (`t-c2c4dddb`) built that command. It writes `null` with
`rank_status: "unmeasured"` on every machine but the candidate's — D-2's third
outcome, and the honest one: the ordering lives in the candidate's own profile
store and is never committed here.

## Tests

Write these RED before any production code:

`test_ranking_correlates_with_manual_order` in `tests/test_calibration.py` — Spearman ρ ≥ 0.60 against the recorded manual order.

Not written by T20a, deliberately: the assertion is about a real candidate's
real ordering, and a version of it over a fixture would assert that arithmetic
this task does not own still works. T20a covers the arithmetic
(`test_spearman_matches_a_known_order`); this one belongs to the sitting.

## Location

Service: **MATCH** · Size: M

Design: `status/plan.md` (T20) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`

## The harness is T20a, and it is not this task

Split out on 2026-08-24. Everything except the act of ranking — drawing the 20
from the evaluation split, presenting them blind, recording the ordering, and
computing `rank_spearman` — is **T20a** (`t-c2c4dddb`), which no human needs to
be present for.

This task was unbuildable as filed. Its `bash` block was the placeholder that
fails on purpose, `tests/test_calibration.py` did not exist, and there was no
Spearman implementation in the tree — so a candidate sitting down to do T20 had
nothing to do it with. And because `requires: [surface:human]` excludes this
task from the selector, no agent would ever have written that software either:
the missing 90% was invisible to both halves of the system.

**T20a has landed.** The gate block above now runs
`integral.calibration spearman`, `tests/test_calibration.py` exists, and
`status/evidence/T20.json` reports `unmeasured` until a candidate sits down.
What remains here is the act of ranking, which is the whole of what `[HUMAN]`
meant.

**T20a replaces the placeholder** with
`uv run python -m integral.calibration spearman status/evidence/T20.json` as part
of its own work. When this task is claimed, the gate below should already say
that; if it still says "no gate command defined", T20a has not landed and this
is not ready.

The ordering you give is recorded in the **profile store**, not in this
repository — it is a statement about you, not about the ads. What gets committed
is the scalar `rank_spearman`. Until you have ranked, that number is `null` with
`rank_status: "unmeasured"` everywhere, which is D-2's third outcome and not a
failure.

## Human-owned

Requires the candidate personally. Carries `requires: [surface:human]`, a
capability no surface declares, so the selector excludes it by default — the
`human` tag alone would not, since tags only filter when LOOP_TAGS is set.
