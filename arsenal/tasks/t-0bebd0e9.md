---
id: t-0bebd0e9
title: "T270: Offers: stored offers with an unvalidatable salary.period survive #538's backfill"
priority: 5
requires: [human:gate]
---

Imported from issue #543

## What happens

`load_offer()` raises on offers whose `salary.period` is outside the enum:

```
Input should be 'year', 'month', 'week', 'day' or 'hour'
```

Observed values: `'annual'`, `'HOUR'`. In one candidate store **68 offers** are
in this state, so any audit or ranking that walks the tree with `load_offer()`
dies on them rather than on the one bad record.

f806c8e5 (#538) backfilled offers written before T170 with a raw
`salary.period`, which is why this is worth a task rather than a one-line fix:
the backfill ran and these records came out the other side still unloadable. So
either the backfill's population is narrower than the defect's, or it writes the
raw value through without normalising it.

## Two things to decide, and they are separate

1. **Normalisation.** `'annual'` → `year` and `'HOUR'` → `hour` are unambiguous;
   normalise on read (casefold + a small synonym map) rather than requiring every
   connector to have got it right at write time.
2. **Blast radius.** A single unparseable offer currently takes down the whole
   walk. Whatever reads a directory of offers should report the bad record and
   carry on, so one malformed file cannot hide the other 117.

(2) is the one that matters even after (1) is fixed — the next unexpected value
should cost one line of output, not the run.

## Acceptance gate

```bash
uv run pytest tests/test_offers.py -q
uv run python -m integral.repo_gate
```

Fixtures: a stored offer carrying each observed raw value loads and round-trips;
a stored offer carrying a genuinely meaningless period is reported and skipped
without aborting a directory walk.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
