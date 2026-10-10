---
id: t-f7debe60
title: "T301: T237 follow-ups: dead n=0 past-the-end case; summary should name next offset"
priority: 5
requires: [human:gate]
---

Imported from issue #702

Optional findings from the second read of #700 (round 2, comment 5974799606):

- **O1**: the `n=0` case of the past-the-end test builds `Aim(state="stated", terms=())`, which pydantic rejects with a ValidationError before `source()` runs. So that case never reaches the check it names; it stays green with the check removed. Fix: use `Aim(state="unknown")`.
- **O2**: a caller passing the leftover phrases at `offset=0` still gets that slice saved as the aim. Code cannot tell this apart from a legitimately narrowed aim. Nudge: have `Run.summary()`'s "NOT searched" line name the `offset=` value for the next pass.

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
