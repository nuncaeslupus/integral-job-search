---
id: t-54e6a7ac
title: "T303: T236 follow-ups: gap may name any open task; sourcing fills employer only on falsy company; MINIMUM_GAPS"
priority: 5
requires: [human:gate]
---

Imported from issue #706

Optional notes from the second read of #704, round 2 (comment 5975679403):

- **N1**: `employer_gap` accepts any open task, e.g. an unrelated `T233`. A cheap guard: require the named plan row to mention the connector's site.
- **N2 (latent, fail-open)**: `_one_board` fills `{employer}` only when `company` is falsy. A whitespace-only or Cf-only company is therefore stored blank, while the gate credits the row. Fix: use `not names_an_employer(item.get("company"))` in `_one_board`. No committed fixture hits this today.
- **N3**: `MINIMUM_GAPS = 1` requires that a gap exists. T235's PR will turn it red by construction and have to delete it. Consider dropping it now.
- From round 1, **O1**: the count is taken after the topic exclusion, so it counts offers kept rather than offers built. This is fail-closed, and a mutant that moved the count was not caught.

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
