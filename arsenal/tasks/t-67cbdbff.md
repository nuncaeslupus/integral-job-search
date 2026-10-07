---
id: t-67cbdbff
title: "T291: State-home backup and OS defaults: follow-ups deferred from T193 (#675)"
priority: 5
requires: [human:gate]
---

Imported from issue #676

These three items were deferred from the review of PR #675 (T193). The review's round-1 report is issuecomment-5968486730.

- **F3:** the backup can "succeed" while holding no data. This happens when `profiles/` is a symlink, when a nested repository sits inside the state dir, or when the user's global gitignore excludes the files. The script should verify that the commit actually contains the candidate's files.
- **F5:** `tools/backup_state_home.sh` exits 2 on `INTEGRAL_HOME='~/x'`, while the Python resolver `candidate_root()` expands `~`. The two disagree. This fails closed.
- **F6:** on macOS and Windows, nothing migrates existing data from the old `~/.integral-job-search` location to the new platform default. That recreates the "profile invisible" problem T193 started from. Either detect and migrate the old location or warn about it.

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
