---
id: t-246f6dde
title: "D-29: status/plan.md's milestone rows still list 82 merged tasks, and the contract saying they don't is enforced by nothing"
priority: 5
---

Imported from issue #314

`status/plan.md`'s merge-order section states a contract:

> Merged tasks (T1–T4b, T23) are not listed; every open task appears in exactly one milestone.

Nothing enforces it, and it is now false for **82 of the 89 labels** the six milestone rows list. Measured against `arsenal/tasks/_history/*.md` (each archived file carries `status: merged`, which `effective_state` reads):

| milestone | listed | merged but still listed |
|---|---|---|
| M1 — the spine | 10 | **10** |
| M2 — L1, a rough list end to end | 18 | 16 |
| M3 — L2, the full first run | 18 | 17 |
| M4 — per opportunity | 21 | 19 |
| M5 — contact with the world | 19 | 17 |
| cross-cutting | 3 | **3** |

M1 and cross-cutting are entirely merged and entirely still listed. The parenthetical `(T1–T4b, T23)` is a snapshot of what had merged on the day the sentence was written, and it has not moved since; the sentence around it reads as an invariant.

**How this surfaced, and why the shape matters.** CodeRabbit flagged D-24 in the M4 row on #305 — correctly, by the letter of the contract. But D-24 is one of 82, and the same row still lists T46, merged long ago. Removing the single row a reviewer happened to look at would make the file marginally less wrong while leaving the stated invariant false, and would leave nothing to catch the next one. That is the same move already declined once this session for the plan ticks, where 47 of 123 archived-merged tasks had unticked rows and hand-ticking T101 inside T103's diff was the tempting non-fix (filed as #308).

This is the third instance of one pattern: **`status/plan.md` states things about the task graph that no gate reads.** The ticks (#308), and now the milestone rows. Both drift silently because the plan is prose to every check that exists, and the archive is the only thing that actually knows a task is done.

## Acceptance gate

<!-- `## Acceptance gate`, not `**Acceptance gate**`. `gate_evidence.py:74`
     matches `##\s+Acceptance gate` and takes the FIRST match; a bold label is
     not a heading, so the block below was invisible to it and the task passed
     with nothing read. `verify_gates.py:115` meanwhile decides "declares a
     gate" from the substring ```` ```gate ````, which was true — so the two
     readers disagreed and the disagreement resolved to PASS. Found by the
     second read of #334. -->

```gate
milestone_row_membership_violations == 0
evidence: status/evidence/D-29.json
key: milestone_row_membership_violations
```

Derive merged state from `arsenal/tasks/_history/*.md` (`status: merged`) and never from the plan's own ticks — a check that reads the document it is checking measures nothing. The denominator is the number of milestone-row labels evaluated, and `gate_status` must be `unmeasured` when the archive cannot be read or resolves no labels, rather than reporting the clean zero an empty scan produces. A **floor** on the labels scanned, in the `naming.MINIMUM_SCANNED` style, not a count of the day — the count moves on every task PR and would drift by construction (T100).

Worth folding #308 into the same module if that task has not started: both gates read the same archive and answer the same question about the same file, and two modules disagreeing about which tasks are merged would be its own defect.

**The exit-3 shape applies.** `Makefile:58-70` maps exit 3 to `unmeasured (recorded)` and **continues**, so returning 3 on a floor breach does not fail `make evidence` — return 1. And do not let `record()` write the claim before the check runs (#297: both `task_gate` and `plan_v2` had the write-before-check hole, and a test was asserting the false claim was present).

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
