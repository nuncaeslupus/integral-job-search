---
id: t-aa3ce632
title: "T165: the floor census ignores the comparison operator, so five ceilings are counted as floors"
priority: 5
deps: [t-6f2b9c14]
tags: [ARSENAL]
workspace: BACKEND
---

## Acceptance gate

```gate
bounds_counted_with_the_wrong_polarity == 0
evidence: status/evidence/T165.json
key: bounds_counted_with_the_wrong_polarity
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_floor_sweep.py -q
uv run --extra dev python -m integral.floor_sweep
```

## The defect

`_compare_sites` records where a constant is compared against a size and ignores
**which way the comparison runs**. So a ceiling is indistinguishable from a floor,
and five of them sit in the floor census: `GENERATION_CAP`,
`MAX_EXTRA_EPISODE_ATTEMPTS`, `DETAIL_FETCH_CEILING`, `_SHINGLE`, and
`_CONFIRMING_MATCHES_FOR_BIPOLAR`.

A ceiling and a floor fail in opposite directions. A rule that cannot tell them
apart is asserting something about a population it has not identified — and the
"first deletion must breach" test is **meaningless** for a ceiling, which is
breached by addition.

## What the metric counts

`bounds_counted_with_the_wrong_polarity` is the number of committed bounds the
census classifies as floors whose comparison establishes an upper limit, plus any
classified as ceilings whose comparison establishes a lower one.

Polarity is derivable from the comparison node — this is a closed rule over the
AST, not an enumeration of constant names.

The bounds read are the denominator, a **literal** floor per T122.

**Verify the metric is non-zero against today's tree before writing the fix** —
it should find at least the five above.

## Also in scope

The **55 floor-shaped names T159 ruled out of scope and never judged** need
adjudicating, and polarity is what most of that adjudication turns on: a name
that looks like a floor and bounds from above was never this census's business.
Record each as floor, ceiling, or neither, with the reason.

## Scope

* Independent of T163 and T164 — polarity is decidable from the source with no
  margin argument and no declared population.

Filed from the second-reader report on #436.
