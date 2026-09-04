---
id: t-f1d664eb
title: "T119: a draw re-issued over a full corpus collects nothing and exits 0"
priority: 5
---

## Acceptance gate

```gate
draw_shortages_counted_outside_the_draw == 0
evidence: status/evidence/T119.json
key: draw_shortages_counted_outside_the_draw
```

Transcribed from `status/plan.md`'s row for this task, which declared this
metric before the task was imported. The name is the plan's, not a new one:
inventing a second name for a declared metric is a mistake this repository has
made four times, and `test_the_committed_plan_and_queue_agree` fails it.

Imported from issue #316

`tools/collect_ads.py` now binds two of a draw's three axes: `sources` and
`job_families` narrow the plan before anything is fetched (#307). The third —
the counts — still does not bind, and that is a real gap.

`--target-es 60` is read against **every** row in `corpus/raw/ads.jsonl`,
whatever draw produced it:

```python
missing = target - language_counts(list(ads.values()))[lang]
if missing > 0:
    absorb(name, fetch(session, missing))
```

So a draw re-issued over a corpus that already holds enough rows collects
nothing and exits 0. The run reports success over a sample it never took —
which is the failure mode this whole milestone exists to stop, arriving through
the collector instead of through a gate.

Concretely: `t4b-programming` put 100 rows in. A later `t25-families` run sees
`es` already at 60 and `ca` at 15, fetches no language rows at all, and the only
thing that saves it is the family loop, which counts by family rather than by
language. A third draw sharing a family with an existing one has nothing
saving it.

## Why it was not fixed in #307

Narrowing the source and family axes only ever *removes* requests, so it cannot
import a row `corpus_scope.draw_selects` would refuse — it is safe by
construction. Draw-scoped counting is not: it changes what `--target-es` means
(sixty rows in the corpus, or sixty rows in this draw?), and the answer decides
whether two draws sharing a language double the corpus or share its rows. That
is a specification question, not a patch.

## Acceptance

Shortages are computed over the rows belonging to the selected draw, `--target-*`
documents which of the two readings it is, and a fixture shows a re-issued draw
collecting its sample over a corpus that already satisfies the global count.

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
