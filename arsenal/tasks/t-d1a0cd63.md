---
id: t-d1a0cd63
title: "Every open task PR goes stale on D12 the moment any other task PR merges"
priority: 5
requires: [human:gate]
---

Imported from issue #288

Measured across #283, #284, #285, #286 and #287 today.

## What happens

`status/evidence/D12.json` counts the gate blocks it can read — `evidence_gates_read`, `gates_declaring_status_key` — across `arsenal/tasks/` **and** `arsenal/tasks/_history/`. A task PR adds one gate block. So the moment any task PR merges, main's D12 gains a row, and **every other open task PR's committed D12 is correct for its own branch and stale for its merge commit**.

CI checks out the *merge* ref, not the branch, so this lands as:

```
 status/evidence/D12.json | 4 ++--
evidence: committed evidence does not match what the code measures now
```

on a PR whose author changed nothing and whose own `make host-gate` is green. It happened to #284 and #285 when #283 merged, and to #286 when #284 merged.

## Why this is not T100

T100 (#284) fixed a denominator committed as an exact value — `T55.files_scanned` — where the *archive* moved the number. This is a different axis: the number moves because **someone else merged**, and no floor helps, because the count is what D12 is measuring rather than a guard against an empty scan.

## Cost

It is quadratic in open task PRs, and it is charged at exactly the wrong moment. Each merge forces `git merge origin/main && make evidence && git add -A && git commit && git push` on every other open PR, which restarts CI **and** restarts the review bot — so the more parallel the queue, the slower each PR clears. With five PRs open today it cost more session time than any single review finding.

It also trains a bad reflex: a red `evidence is current` that means nothing about the PR is the same signal as one that means everything, and CLAUDE.md already had to be rewritten twice about a red that says the wrong thing.

## Shapes a fix could take

Not a recommendation — the trade-offs need someone to weigh them:

1. **Regenerate rather than compare, for aggregate-only keys.** Let CI recompute D12 and diff only the keys that are not pure counts of task files. Keeps the drift check meaningful for measurements while dropping it for a census of the queue.
2. **Make the counts a floor**, the T100 move — but the counts here are the finding, so a floor weakens it.
3. **Exclude `D12.json` from the drift gate and assert it in `verify-gates` instead**, where it is already recomputed against the live task files.
4. **Have `arsenal-queue.yml` refresh evidence on open PRs after a merge** — automates the churn rather than removing it, and still restarts every review.

Option 1 or 3 look closest to the repository's own reasoning about what a denominator is for; both need checking against what D12 exists to catch.

Filed from the session that hit it five times, rather than worked around a sixth.

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
