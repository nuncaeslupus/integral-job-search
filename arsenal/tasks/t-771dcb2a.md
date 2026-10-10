---
id: t-771dcb2a
title: "T302: T225 follow-ups: unmeasured plan metric, purge drops hold-back, over-merge risk"
priority: 5
requires: [human:gate]
---

Imported from issue #703

Optional findings from the second read of #701 (comments 5974687624 and 5975116911):

- **F3 (stand-in for the property)**: the plan row is ticked against `ruled_out_adverts_presented_again_under_another_id == 0`, but nothing computes that metric. This is the same as #698 F5.
- **F4 (latent)**: once a ruled-out or presented copy is purged, it stops holding back its siblings, because tombstones carry no title or company. This extends #698 F2. Nothing calls `purge_offer` today.
- **F5 (minor)**: when a copy is held back by an exclusion, its twin in the same batch is not deduped against it.
- **F2 remainder**: `posting_key` still splits on trailing punctuation and on company suffixes ("ACME" vs "ACME S.L."). The code documents this as a choice against over-merging.
- **Over-merge (hides adverts, not repeats)**: grouping whole chains means one wrong link merges two groups. Likely causes are a talent URL with no `id` (#698 F4), or a chain employer posting one generic title in many cities. Worth a guard or a documented limit.

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
