---
id: t-c9a7faac
title: "T300: T244 follow-ups: optional findings from the #693 second read"
priority: 5
requires: [human:gate]
---

Imported from issue #699

These are the optional findings and recorded trade-offs from the second read of #693 (T244, merged as f58b512). None of them blocked the merge.

- **G3.** `fit_seniority` averages the title cues, so a misleading title (for example "Senior Volunteer Mentor") can pull the level. The implementer left this as is and gave a reason; the reviewer accepted it as optional.
- **Behaviour change to confirm with the owner.** Adjacent roles with year-only dates (junior 2015–2020, senior 2020–present) now read as ambiguous, and `fit_seniority` falls to 0.2. This is conservative (fail-closed) but may under-rank real seniors whose CVs use years only.
- **Unpinned.** The rule for a shared end-of-span when both roles carry only a year is covered only by the adjacent-years test.

Reports are on #693 (rounds 1–5).

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
