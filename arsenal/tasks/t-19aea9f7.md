---
id: t-19aea9f7
title: "T299: T224 follow-ups: optional findings from the #697 second read"
priority: 5
requires: [human:gate]
---

Imported from issue #698

These are the optional findings from the second read of #697 (T224, merged as 6135e3e). None of them blocked the merge.

- **F2 (latent, fail-open).** The read-time merge in `presentation_log.partition` reads only stored offers, never tombstones. If a `screened_out` copy is purged (it becomes eligible at 60 days), a sibling copy stored before T224 is shown again. Nothing calls `purge_offer` today.
- **F4 (fail-closed, unreachable today).** A talent URL with no `id` collapses to the bare `/view`, which would merge every such advert into one. Every fixture URL carries `id`.
- **F5 (proxy, not property).** The plan row is ticked against `offers_stored_more_than_once_by_canonical_url == 0`, but nothing computes that metric. The real store still holds its pre-existing duplicates (139, from the issue), because there is no migration. This overlaps T225 (#628).
- **O1.** `canonicalize_url` keeps `www.` and default ports, so `jobfluent.com/...` and `www.jobfluent.com:443/...` still split from the board's copy. This predates T224.
- **O2.** For a host no connector names, the declaration falls back to `source`. A `source=jobfluent` URL on a foreign host would have its query dropped. This fails closed, and nothing produces such URLs today.
- **Untested path.** The shared-host union rule (any connector undeclared → keep the whole query) is never exercised, because no host is shared by two connectors yet.

Reports: comments 5973397411 and 5973652773 on #697.

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
