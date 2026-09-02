# Session handover

Board: **162 tasks, 126 merged**, 28 open, 4 claimed. Five PRs open, all green,
all waiting on the same thing.

## The one thing to know: `after-ci-and-review`'s review half has no reader

`merge-policy` is `after-ci-and-review`. CI is checked mechanically. **Nothing
reads the review half**, and CodeRabbit reports a green check in four distinct
situations where it has not reviewed the head:

1. `Review skipped: draft pull request`
2. `Review rate limited`
3. `Review completed` — on a **superseded** commit
4. `@coderabbitai review` → `✅ Action performed — Review finished`, producing
   no review at all. Its own note says the command applies "only when automatic
   reviews are paused", and a review that *bounced off the rate limit* was never
   paused. **The working command is `@coderabbitai full review`.**

The only signal that survives all four is a review object whose `commit_id`
equals the head:

```bash
R=nuncaeslupus/integral-job-search
h=$(gh pr view $N --json headRefOid --jq .headRefOid)
gh api repos/$R/pulls/$N/reviews \
  --jq "[.[]|select(.user.login==\"coderabbitai[bot]\")|select(.commit_id==\"$h\")]|length"
```

Filed as **D-28** (#313). Until it is built, that query is the gate, run by hand.

**Inline-comment count is not a proxy for "nothing found."** #295's review
reported 0 inline comments and carried a real defect in the body as an *outside
diff range* comment. Read the body.

## Quota, measured

**8 included reviews per hour**, Plan Team, profile CHILL — per hour, not per
day. Every push queues a re-review. The rate-limit reply carries
`next included review will be available in N minutes`; parse that rather than
polling on a flat interval.

`tmp/` has no pump script — the one this session used lives in the scratchpad.
Rewrite it from the shape above: request `@coderabbitai full review` on the
highest-priority PR with no review on head, read `N` out of the refusal, sleep
`N+1` minutes. Require a *numeric* review count before treating a PR as
reviewed: `[ -z "$resp" ]` after a grep fires on API failure as well as absence,
which is the exit-3 fail-open shape in a shell script. And **zsh does not
word-split unquoted variables** — build the target directly, never
`echo $pending | tr ' ' '\n' | head -1`.

## Open PRs

| PR | task | head | waiting on |
|---|---|---|---|
| #295 | T89 usajobs POST connector | `4286dec` | review on head |
| #297 | T104 D12 staleness | `f561956` | CI, then review on head |
| #305 | D-24 retraction (+ D-26 task file) | `4fa5e23` | review on head |
| #307 | T98 corpus is a measurement set | `754797a` | review on head |
| #312 | T92 salary recovery | `d1a2f0d` | review on head |

**Merge #297 first.** T104 is what stops every other open PR going stale on
`status/evidence/D12.json` and `S8.json` when anything merges. Measured three
times in one hour this session: a commit touching no code forced a refresh on
two PRs, and each refresh is a new head and another review out of the eight.

## Patterns this session kept finding

- **Exit 3 fails open.** `Makefile:58-70` maps exit 3 to `unmeasured (recorded)`
  and *continues*; only `*)` fails. A module returning 3 on a floor breach does
  not fail `make evidence`. **Return 1.** Still open in `naming._main` (T115).
- **Write-before-check** — `write_evidence` calling `record(measured)` before
  validating floors.
- **A denominator committed as an exact value** drifts on unrelated merges. Use
  a floor (`*_at_least`). T55, T100, T104, and T111 is the next one.
- **A metric named after one direction of a two-direction contract.** D-29's
  gate measured only "merged tasks still listed" while twelve open tasks sat in
  no milestone row. Widened to `milestone_row_membership_violations`.
- **An exclusion with no counter.** D-26's gate excluded sent versions and
  counted nothing, so a growing excluded set — or a version misclassified as
  sent — would have been silence. Every exclusion gets its own reported key.
- **Fixing a fail-open can open a fail-closed hole one layer out.** T92 round 1
  made `Recovered.__post_init__` raise and `recover_all` did not catch, so one
  bad estimator ended the batch.
- **`status/plan.md` states things about the task graph that no gate reads.**
  Four instances now: plan ticks (D-27, 47 of 123), milestone rows in both
  directions (D-29, 82 of 89 merged-still-listed and 12 open-unlisted), and a
  task file's `deps: []` contradicting its plan row.

## Twelve open tasks are in no milestone row

`T56, T57, T59, T69, T89, T91, T92, T94, T98, T102, T105, T106` — pre-existing,
not from this session's seeding (those fifteen are placed). Deliberately not
assigned: a milestone is a statement about build order and it was not this
session's call to make twelve of them. Recorded in **D-29**'s row with the
number, so the gate that lands there has a denominator to beat.

## Queue

The fifteen issues filed this session are seeded (T107–T118, D-27, D-28, D-29).
A bare `issue_import.py --apply` is **not enough**: `plan_v2.measure` requires
the task title to start with a label and a matching row in `status/plan.md`, and
without both `make test` goes red on `test_the_committed_plan_and_queue_agree`.
Label the issue *and* its task file, then write the plan row.

`t-d1a0cd63` and `t-e4047287` report "no issue handle" — both archived; noise,
not a blocker.

## Candidate deliverables

Both Spanish reports are complete in the scratchpad and await owner review.
Step-0 `.active.json` binding is **per-session** and must be re-run next
session. Nothing goes out before the owner reads it.
