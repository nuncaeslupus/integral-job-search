---
id: t-ceebb241
title: "T337: usajobs_en stops at page 2 of 3"
priority: 5
requires: [human:gate]
---

Imported from issue #778

From the second reader on #764 (T152). The committed page-2 response says `NumberOfPages: 3`, and `max_pages: 2` stops short of it with only a YAML comment as the reason. Either capture page 3 and raise `max_pages`, or record the cap as a measured, stated limit. Related: detecting that a response names a further page is still a list of pager spellings, covering the boards T113 dropped but not closed over every pager.

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
