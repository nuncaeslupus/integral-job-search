# Session handover

Board: **163 tasks, 127 merged**. **T104 (#297) is merged** — the staleness
quadratic is over. Four PRs open, all green, all waiting on a review.

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
Rewrite it from the shape above, and from the **three separate ways it wasted
capacity before it worked**, because each is easy to reintroduce:

1. **It nudged into a closed window.** A nudge while rate-limited requests
   nothing and posts a bounce comment. Read CodeRabbit's own clock out of the
   reply and hold. Parse the *unit*: the reply says "3 seconds", "40 seconds"
   **or** "19 minutes", and a regex matching only minutes sent a 40-second wait
   into the hour-long fail-safe.
2. **It had no notion of a review in flight.** CodeRabbit acks a trigger before
   the review object exists, so between the ack and the review a PR looks
   exactly like one nobody asked about — and the second nudge spends a second
   included review on the same head. Hold ~10 minutes after
   `Full review triggered`.
3. **A bounced nudge started the per-PR interval.** So the PR whose request was
   *refused* was made to wait longest, which is backwards. Only a nudge that was
   actually accepted should start that clock.

Require a *numeric* review count before treating a PR as reviewed: `[ -z "$resp" ]`
after a grep fires on API failure as well as absence, which is the exit-3
fail-open shape in a shell script. And **zsh does not word-split unquoted
variables** — build the target directly, never
`echo $pending | tr ' ' '\n' | head -1`.

## Open PRs

| PR | task | head | waiting on |
|---|---|---|---|
| #295 | T89 usajobs POST connector | `5d266c6` | review on head |
| #305 | D-24 retraction (+ D-26 task file) | `e0b0527` | review on head |
| #307 | T98 corpus is a measurement set | `bda48bb` | review on head |
| #312 | T92 salary recovery | `a13ba87` | review on head |

**The quadratic is closed.** Merging #297 made all four `CONFLICTING` one last
time — T104 shrank `D12.json` from 1,066 lines to a small record and every open
PR carried the old shape — and after that refresh a merge to `main` no longer
touches them. The record now reads `evidence_gates_read_at_least: 100`,
`gates_declaring_status_key_at_least: 20`, `board_sensitive_record_keys: 0` over
`record_keys_compared: 4`: floors and a sensitivity reading, no census.

`tmp/refresh_pr.sh` does the refresh. **Its `make evidence` step is not
optional.** Resolving an evidence conflict with `git checkout --ours` alone kept
a pre-T104 `D12.json`, and T104's own new guard caught it on the first run after
it merged:

```
t-d1a0cd63: status/evidence/D12.json records board_sensitive_record_keys=None,
which is not a number, and the gate block declares no `status-key` — the gate
reads the one honest measurement as a hard failure
```

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
- **A gate that does not select its own fixtures.** D-24's block is
  `pytest tests/test_approval.py -k retract`, and the two fixtures written to
  hold this PR's *own* accepted findings were named for what they assert, not
  for the keyword that reaches them — 23 of 48 selected, both in the deselected
  25. Committing an accepted case to the file is half the rule; the gate has to
  run it. Only two gate blocks in the queue use `-k`, and the other one is
  correct, so this is an instance rather than a pattern.
- **A header lookup that skips instead of failing.** `recorded.headers.get("Content-Type")`
  against a recorded `content-type:` returns `None`, and the guard was
  `if expected_type is not None` — so a form POST the engine cannot issue was
  reported by `why_unreadable` as a board with no gap. An empty result from a
  "name every problem" function means *no problem*, so any lookup feeding one
  must fail closed.
- **A required flag that validates but does not constrain.** `collect_ads.py
  --draw` was checked against the registry and stamped onto every row, while the
  plan still contacted every board and searched every family. `t25-families`
  names one board and put four on the wire. The rows would have been refused by
  `corpus_scope.draw_selects` — but *after the request had been sent*, which is
  the half a fail-closed data path does not cover.
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

**#316** was filed this session and is not yet seeded: a draw re-issued over a
corpus that already meets the global count collects nothing and exits 0.
Deliberately not fixed in #307 — draw-scoped counting changes what `--target-es`
means (sixty rows in the corpus, or sixty in this draw?), and that answer decides
whether two draws sharing a language double the corpus or share its rows. It is a
specification question, and settling it inside a review round is how an
implementation sets a specification.

## Candidate deliverables

Both Spanish reports are complete in the scratchpad and await owner review.
Step-0 `.active.json` binding is **per-session** and must be re-run next
session. Nothing goes out before the owner reads it.
