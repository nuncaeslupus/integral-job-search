---
id: t-c2d5ad8b
title: "T305: Follow-ups from T235 (#708): foorilla location markers and truncated place lists"
priority: 5
requires: [human:gate]
---

Imported from issue #710

Optional findings from the second reader on #708, not done there:

- O2: map foorilla's `[R]` / `[WH]` marker in `location.raw` to `location_remote` (needs a `first_text_node`-style `take` or a post-parse).
- O3: multi-place cards are cut by the board with "…"; check whether the advert page carries the full place list.
- T235 plan-row metric `foorilla_offers_without_location` is a label no evidence computes; consider naming the pinning test in the cell (as T236/T237 do).

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
