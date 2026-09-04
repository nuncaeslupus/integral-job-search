---
id: t-ed41cbe3
title: "T115: naming._main's files_scanned floor exits 3, which make evidence records and continues"
priority: 5
---

## Acceptance gate

```gate
floors_that_do_not_fail_the_gate == 0
evidence: status/evidence/T115.json
key: floors_that_do_not_fail_the_gate
```

Transcribed from `status/plan.md`'s row for this task, which declared this
metric before the task was imported. The name is the plan's, not a new one:
inventing a second name for a declared metric is a mistake this repository has
made four times, and `test_the_committed_plan_and_queue_agree` fails it.
Imported from issue #309

Flagged by the session fixing the T104 second-reader findings (#297), which deliberately scoped its own fix to `task_gate` and `plan_v2` rather than widening into this.

## The defect

`integral.naming._main` returns **3** when the `files_scanned` floor is breached. `Makefile:58-70` maps exit 3 to `"unmeasured (recorded)"` and continues; only `*)` fails. So a floor breach in `naming` does not fail `make evidence`, and `make host-gate` stays green over a scan that did not happen.

This is the same shape accepted as **D-1** on #297, where it was blocking:

> `make host-gate` is fully green on a board where 126 of 131 gates were never read.

There it was load-bearing because the drift check *was* the live guard for D12 and S8. Here it is one step further from the edge — but `files_scanned_at_least` is T100's whole anti-vacuity mechanism, and a floor nothing enforces is decoration.

## Why it was not fixed in #297

Flipping it breaks `test_an_empty_scan_still_fails`, which asserts `exit_code == 3` and is **named in T100's plan row**. So this needs the test, the plan row and the exit code changed together, which is more than a review fix should carry.

## Scope

Return 1 rather than 3 on a floor breach, matching the resolution taken on #297 — a floor breach is a *finding* (the sweep ran, counted, came back short), not the absence of a measurement that exit 3 denotes. Update `test_an_empty_scan_still_fails` and T100's Tests column in `status/plan.md` in the same diff.

Then check the remaining evidence modules for the same shape rather than fixing the three that are known — a floor that exits 3 is decoration wherever it appears.

## Gate

`floors_that_do_not_fail_the_gate == 0`, over every evidence module that asserts a floor, with the count of modules examined as the denominator.

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
