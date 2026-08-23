---
id: lo-bbc7
title: "T18: Pareto frontier + salary-equivalent ordering + facet lists"
priority: 1
deps: [lo-bacf, lo-25b1]
workspace: MATCH
tags: [m2]
---

## Acceptance gate

```gate
pareto_dominance_violations == 0
evidence: status/evidence/T18.json
key: pareto_dominance_violations
```

```bash
uv run python -m integral.rank status/evidence/T18.json
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T18.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_dominated_offer_never_appears_in_frontier` in `tests/test_rank.py` — an offer worse on every dimension is excluded; `test_unknown_dimension_is_not_treated_as_neutral` — an unknown score does not count as average

## Location

Service: **MATCH** · Size: L

Design: `status/plan.md` (T18) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`

---

## Scope change — v2 plan, 2026-08-18

A ranking now **records the `profile_revision` and the sufficiency level that
produced it** (`status/spec-v2-process.md` §3.1, §3.4), and is labelled with the
level wherever it is shown. Without weights the ranking is **L1** — hard filters
plus default weights — and says so. A provisional ranking that is not labelled
provisional is a defect, not a shortcut.

A ranking whose pinned revision is behind the current one is displayed as out of
date with a one-click recompute; staleness is computed by T37 rather than
tracked here.

Presentation — the offer card, the handful at a time, unknown shown as unknown —
is **T44**, and it is half of step 9's specification rather than a rendering
detail.
