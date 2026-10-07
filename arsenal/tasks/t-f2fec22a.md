---
id: t-f2fec22a
title: "T263: open_task_pr.sh's gate ordering makes a task whose own gate runs `make evidence` red on one side or the other by construction"
priority: 5
requires: [human:gate]
---

Imported from issue #489

Two independent workers hit the same class of friction on 2026-09-15, on unrelated tasks (T162 `t-854bbf35`, T170 `t-6fdc0bc7`). Neither is a defect in their diffs; both are in the helper, and both cost a full-suite run or more to discover.

## 1. The archive/tick ordering trap

`open_task_pr.sh` runs **the task's own acceptance gate before archiving** the task file, then runs **`make host-gate` after** archiving.

D-27 requires that a task archived in `arsenal/tasks/_history/` with `status: merged` carries a ticked `☑` row in `status/plan.md` — and `make evidence` enforces it.

So for any task whose own gate block runs `make evidence` (several do), the two runs demand opposite trees:

| run | tree state | wants the plan row |
|---|---|---|
| task gate (pre-archive) | task file still in `arsenal/tasks/` | **unticked** |
| `make host-gate` (post-archive) | task file in `_history/`, `status: merged` | **ticked** |

Ticking at either "normal" moment fails one side. The worker's workaround was to archive and tick **by hand before invoking the script**, so `_archive_task_file` no-ops and both runs see a consistent tree. That works, and it is exactly the kind of undocumented pre-step that the repo's own CLAUDE.md warns turns into a re-derived workaround nobody can audit.

Candidate closing forms, in preference order:
- run the task's own gate **after** the archive too, so there is one tree and one answer; or
- have the script perform the plan tick itself as part of `_archive_task_file`, so the archive and the tick are one atomic step and cannot be sequenced wrongly.

## 2. `make evidence`'s drift check compares against the index, not HEAD

When evidence files legitimately need regenerating for a changed module, the regenerated content only compares clean after `git add -A`. A worker hit two failed `open_task_pr.sh` attempts before staging, each costing a full suite run.

This may be intended, but it is not written down anywhere a worker reads, and the failure presents as evidence drift rather than as "you have not staged".

Either is cheap to fix and each one currently costs a worker several minutes of full-suite time to rediscover.

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
