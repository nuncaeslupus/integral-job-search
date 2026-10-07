---
id: t-c391ca8f
title: "T334: Step 7 calls alert_mailbox.refusal before reading any job-alert email"
priority: 5
requires: [human:gate]
---

Imported from issue #773

T247 (#771) adds `integral.alert_mailbox`: a per-read permission ledger and `refusal()`, the single enforcement point. Nothing in the offer path calls it yet — the rule is stated in the step-07 skill and measured over a constructed population only.

Wire it: whatever reads a job-alert email as a source asks `refusal()` first and reads nothing when it refuses. Gate: a metric counting alert reads that reached the offer path without a recorded permission, over real call sites rather than a constructed ledger.

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
