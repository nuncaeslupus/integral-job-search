---
id: t-fbdae165
title: "review: Unsteerable employer boards are downloaded in full on every run"
priority: 5
requires: [human:gate]
---

Imported from issue #932

**Severity:** medium · **Confidence:** medium · **Category:** performance

**Where:** `src/integral/sourcing.py:1155-1203, src/integral/sourcing.py:1604-1608, connectors/greenhouse_en/connector.yaml, connectors/ashby_en/connector.yaml`

### Finding
Greenhouse/Ashby/Lever/Workable connectors take no query, so each sourcing run requests every listed employer board (126 URLs, Greenhouse with `content=true`, i.e. every job description) and filters locally with `matches_aim`; nothing is cached between runs and no conditional request is made, so repeated rounds re-download megabytes to add at most `board_cap` offers.

### Evidence
Traced: requests loop only stops early when `added >= limit`; employers per connector counted from YAML (56/57/13/2/1). No ETag/If-Modified-Since or on-disk cache in src (grep).

### Suggested direction
Cache board responses per run day in the state home (or send conditional requests) and let the candidate's aim select a subset of employers.

_From the full repo review of 2026-11-11 (finding #13). Not fixed yet; verify before acting._

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
