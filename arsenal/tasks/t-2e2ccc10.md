---
id: t-2e2ccc10
title: "T309: Follow-ups from #717 (T238 robots retry): optional review findings"
priority: 5
requires: [human:gate]
---

Imported from issue #721

Optional findings from the second reader on #717. None of them blocked the merge.

- **SSL errors:** certificate and SSL errors are retried even though a retry cannot succeed. They could fail straight away.
- **Worst-case wait:** about 64 s per unreachable origin across the retries. A total deadline could cap this.
- **Unpinned wording:** a 403 whose browser retry raises `HTTPException` reports a plain `RobotsError`, not `RobotsUnreachable`. No test asserts that it is *not* `RobotsUnreachable`, so that wording choice is not pinned.

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
