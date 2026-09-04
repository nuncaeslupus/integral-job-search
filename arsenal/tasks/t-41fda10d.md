---
id: t-41fda10d
title: "D-28: `after-ci-and-review` has no reader for the review half — and now no reviewer either"
priority: 5
---

Imported from issue #313. **Re-scoped 2026-09-04**: CodeRabbit is gone — the
account lost it for private repositories and the owner's decision is to go
without. The original text below is kept because its measurements are the
evidence, not because the bot still exists.

## Acceptance gate

```gate
merges_allowed_without_a_review_of_the_head == 0
evidence: status/evidence/D28.json
key: merges_allowed_without_a_review_of_the_head
status-key: review_reader_status
```

The metric is `status/plan.md`'s own and it survives the re-scope unchanged: "a
review of the head" is exactly what a second-reader report on the head commit is.
What changed is only who writes the review.

CLAUDE.md now defines the review half — *a session other than the implementer
reads the PR and reports on it, naming for each finding the input, the verdict and
the section it is derived from; the implementer never signs it off; accepted
findings are committed as fixtures before merge; docs-only PRs are exempt.* That is
a rule in prose, and a rule in prose that nothing reads is the failure this
repository has already recorded four times under "`status/plan.md` states things
about the task graph that no gate reads". **This task gives it a reader.**

Why it is checkable now and was not before: CodeRabbit's signal was unreadable in
five distinct ways, ending with a Free plan that produces a walkthrough and never a
review object at all. A second-reader report is **our own artefact** — a PR comment,
by an author other than the PR's author, carrying a marker naming the head commit it
read. All three are queryable, and the third is the one that matters, because it is
the `commit_id == head` discipline that #320 proved the cost of: nine actionable
findings sat unworked there while the PR read as reviewed, because the only review
object pointed at a superseded commit.

Requirements, each because its absence is a way to report success over work not done:

- **Both denominators reported as floors** (`*_at_least`, T100) — PRs evaluated, and
  reports found. A clean zero over an empty scan is the failure mode.
- **`review_reader_status: unmeasured` and exit 1, never 3**, when the scan cannot
  resolve PRs or markers. `Makefile:58-70` records 3 and *continues*.
- **A report on the wrong commit does not count.**
- **The exempt set has its own counter** — `docs_only_prs_excluded` beside the
  numerator. An exclusion with no counter is silence, and a code PR misclassified as
  docs-only would merge unread with nothing to show for it.
- **Self-review does not count.** A report whose author is the PR author is not a
  second reader; that check is the point of the rule, not a detail of it.

## What it must not become

**Do not satisfy this by lowering the policy.** Setting `after-ci` makes the gate
green by removing the requirement — the same move as dropping the concepts a reader
could not name to raise `ontology_hit_rate`. The owner chose to keep
`after-ci-and-review` with a human-grade reviewer; this enforces that choice rather
than reopening it.

**Do not let the marker be free text.** "Reviewed" in a comment body is what a report
looks like today, and a scan matching prose passes on a comment that says the word and
fails on a thorough review that does not. Define the marker, and have the writer emit it.

---

### The original filing, kept for its measurements

`merge-policy` is `after-ci-and-review` (T103, #304). T103 gave the **CI** half a mechanical reader: `merge_policy.py` reads the latest `CI` conclusion on `main` from a committed capture and refuses to call a merge allowed while it is not `success`.

The **review** half has no reader. Nothing computes whether a review happened; a session decides by looking, and what a session looks at is `gh pr checks`. Measured on #264 at 11:08 UTC today:

```
CodeRabbit	pass	0		Review rate limited
```

And on the same PR twenty minutes earlier, while it was still a draft:

```
CodeRabbit	pass	0		Review skipped: draft pull request
```

Both render as a green tick. The check name is `CodeRabbit`, the bucket is `pass`, and the only thing distinguishing "reviewed and found nothing" from "never looked at it" is a free-text description that `--json statusCheckRollup` does not surface in `conclusion` at all. A session that reads the rollup, sees every check green, and merges under `after-ci-and-review` has satisfied the policy's letter over a PR nobody reviewed.

This is the fail-open shape the repo keeps finding — the same one as #297's exit 3 and #309's `naming._main`: a status that reports success over work that did not happen, producing no drift and no red anywhere. It is worse here than in those two, because the reader is a session rather than the Makefile, and a session's attention is the thing least able to notice a tick that means nothing.

Two things are wrong and they are separable:

**1. The review condition is unreadable.** The honest signal is not the check at all — it is whether `/repos/{owner}/{repo}/pulls/{n}/reviews` holds a `coderabbitai[bot]` entry whose `commit_id` equals the PR's current `headRefOid`. That is the query that distinguishes "reviewed" from "reviewed three pushes ago" as well as from "never reviewed", and neither distinction is visible in the rollup. `merge_policy.py` should read it and report it the way it already reports the CI conclusion, so `after-ci-and-review` has two mechanical halves instead of one.

**2. A rate-limited reviewer is not an absent condition.** CodeRabbit's plan here is 8 included reviews per window (`Review profile: CHILL`, `Plan: Team`), and today's board — six open PRs, several re-pushed after fixes — spent them by 09:36. Every request since has bounced. The policy should distinguish *refused* from *unavailable*: an unavailable reviewer means wait, and the gate should say `unmeasured` rather than resolve either way. This is the `gate_status: measured|unmeasured` discipline the evidence modules already use, applied to the merge condition.

Worth noting the denominator problem too, since it is what made this visible: pushing a fix to a PR queues a re-review, so N open PRs each taking M review rounds costs N×M reviews against a fixed window. The refresh-main churn (#288) multiplies it further. Whatever this issue produces should make the *cost* of a re-review legible, not only its result.

**Acceptance gate, as originally filed** — quoted, not fenced. It named
`status/evidence/T107.json`, which belongs to T107, and T107's own gate now
names it too: two tasks, one evidence file. The live gate is the one in the
front section of this file. Kept as a quotation so the original filing is still
legible without a second fenced block competing to be read.

> `merges_allowed_without_a_review_of_the_head == 0`,
> `evidence: status/evidence/T107.json`  ← wrong file, superseded

The measurement is over constructed states, not over live GitHub: a review on an older commit, no review at all, a rate-limited check reporting `pass`, a draft-skipped check reporting `pass`, and a genuine review on the head — the first four must not resolve to allowed, and the fifth must. Denominator is the number of states evaluated, and `gate_status` must be `unmeasured` when the reviewer's availability could not be determined, never a pass.

The exit-3 shape applies: `Makefile:58-70` maps exit 3 to `unmeasured (recorded)` and **continues**, so a floor breach returning 3 does not fail `make evidence`. Return 1 on a breach, and do not let `record()` write the claim before the check runs (#297).

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
