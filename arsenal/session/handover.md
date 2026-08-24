# Session handover — 2026-08-24, overnight batch

## What merged

Six tasks, all under `merge-policy: after-review`, all with `make host-gate` green
before the merge. Each closed its own issue.

| PR | Task | Gate | Issue |
|---|---|---|---|
| #140 | T22 `methods_ref` link check, both directions | `undocumented_methods == 0` | 54 |
| #141 | T19 explanations citing the advert | `explained_fraction == 1.0` | 58 |
| #142 | T44 the offer card as a filled template | `provisional_rankings_unlabelled == 0` | 66 |
| #144 | D-17 the card renders the stored link | `ranked_offers_without_a_url == 0` | 98 |
| #143 | T21 the feedback loop | `feedback_traceability == 1.0` | 60 |

Board: 95 tasks — **open 2, claimed 1, blocked 4, merged 86** (was 80).

Steps 9 (`ranking`) and 10 (`feedback`) both flipped to `implemented` in
`spec-v2-steps.json`, and both step skills stopped saying their checkpoint "exits
3 at best". T48's drift check and `step_certification` each caught that on their
own — neither needed noticing.

## The one PR still open

**#145 — T43, outside-the-advert enrichment** (`lo-192c`, issue 65). Rebased flat
onto `main`, `MERGEABLE`, `make host-gate` green.

**It has never been reviewed.** CodeRabbit ran out of its ten included reviews
partway through the night and stayed rate-limited through every retry. I did not
merge it, because `after-review` has not happened for it even once — that is a
different situation from the five above, each of which was reviewed and then had
its findings addressed.

To land it: let the review through (billing → usage-based reviews), or say a
session may merge it on the gate alone.

## The review round found four things worth having

Fifteen findings across the six PRs. Twelve real and fixed, three declined with
reasoning posted to the PR. The sharp ones:

- **#143** — `orphaned_reasons` matched reasons to evidence rows with a **set**, so
  one row discharged every event repeating those words. Say the same thing twice
  about one offer, once through the wrapper and once around it, and the bypass
  vanished while the gate read 1.0. Rows are now spent one per event.
- **#141** — a frontier offer with no salary-equivalent total was getting a delta
  anyway. `rank` withholds the total when the salary is missing or a priced
  dimension is unset; `explain` summed whatever drivers it had and published that
  partial sum. It contradicted the PR's own text.
- **#142** — `provisional_rankings_unlabelled` searched the whole page for the
  label, so an unlabelled provisional page would report as labelled if any card
  happened to contain the sentence. It is a header; `startswith` now.
- **#142** — the "unknown is shown as unknown" property was satisfied by `hours`
  and `contract`, which are *unconditionally* unknown, so it would have kept
  passing while pay and location stopped rendering. Each bullet is read off its
  own line now.

Declined, each with reasons on the PR:

1. *Regenerate the ranking artifact after `record_decision`* (#143). A ranking
   needs the live offer set and the dimension list — step 9's inputs, not step
   10's — and `write_ranking` needs a `run_id` this deliberately clock-free
   function does not have. The plan's own named test is
   `test_rejection_moves_offer_status_and_marks_weights_stale`.
2. *Label L2 pages provisional* (#142). Reads the objective backwards: the task
   says *"the **L1** ranking says so"*. An L2 ranking has fitted weights and is
   not provisional; labelling it always would be the same as saying nothing.
3. *Remove the stale placeholder paragraph from the archived task file* (#141).
   Arsenal template text, in **15 of 85** files in `_history/`. Editing one copy
   makes drift. Also already declined once this cycle for the same reason — see
   the previous handover on `_history/lo-b422.md`.

## T26 is now the only thing blocking the queue

`task_select` offers **T26** (`lo-9e41`) and it still should not be taken as
written. Nothing changed; I left it alone. But the situation around it did:

**Four tasks now wait on T26 and on nothing else** — T56 (`lo-6f53`), T57
(`lo-7c14`), T59 (`lo-4b17`), D-19 (`t-e6546af7`). The only other open task is
**T20** (`lo-c48f`), which is `[HUMAN]`: it needs your blind manual ranking of 20
held-out ads. Its dependencies are now satisfied, so it is unblocked and waiting
on you.

So after #145 lands, **the board has no unblocked work an agent can take.**

The decision, unchanged in shape:

- Job (1), widening matched dimensions by corpus sweep, was retired by your own
  2026-08-19 scope change — dimensions are coined when a live session turns one up.
- Job (2), the four candidate-trait dimensions (`side: candidate_trait`, no cues,
  elicited only), is buildable today and independent of both problems.
- T26's gate `ontology_hit_rate >= 0.85` is **`unmeasured`**, and making it
  measurable is T57 — which T26 does not declare as a dep.

**Recommendation**: split job (2) into its own task with its own gate, then either
re-scope T26 to job (1) with `deps: [lo-7c14]` added, or cancel it and let T57
carry the metric. I did not do this: re-scoping a task you already re-scoped once
is a decision, not a chore.

## Environment

- **CI is still out of runner minutes.** Every job fails in ~5s with `runner_id: 0`
  and an empty `runner_name`. Red CI on any of these PRs said nothing about the
  code; `make host-gate` locally is the real gate and every branch passed it.
- **The arsenal bundle is v2.2.1 on `main`** (via the other session's #139), and
  `check_update.sh --check-only` reports **v2.2.2 available**. Not taken.
- **`main` was red when the night started**, and not from anything in flight:
  `handover.md` named a filesystem path that `test_no_document_names_the_old_repository`
  reads as the old repository name, and `T55.json`/`T58.json` carried stale counts.
  The other session had the identical fix staged, so I used byte-identical text and
  the two merged without a conflict. All three came in with #140.
- **The other session merged #133, #138 and #139 mid-run**, which is why the whole
  stack was rebased onto a new `main` around 00:15 and again after each merge.

## `tmp/regate.sh` — new, untracked, worth keeping

Resolves a rebase or cherry-pick that conflicts **only** on `status/evidence/*.json`,
then regenerates every measurement and re-runs the repo gate. Those files are build
products of `make evidence`; merging two versions of one by hand is meaningless —
the right answer is whatever the code measures on the resulting tree. It refuses if
anything outside `status/evidence/` is conflicted, so a real conflict still stops you.

`T55.json` conflicts on *every* rebase (`files_scanned` counts tracked files, so it
moves whenever the index does). The stack was rebased six times tonight; the script
paid for itself twice over. Promote it to the Makefile if this shape recurs.

## Stated ceilings from the merged work

- **`hours` and `contract` can only ever render `unknown`** on the offer card. Step 9
  lists them among the bullets and §5.2's normalised offer has no field for either,
  so no connector can supply one. Making the card say more is a change to the offer
  contract — worth its own task, and the card is honest in the meantime.
- **§4.1 is implemented as an unweighted mean.** The register writes the dimension
  score as weighted by extraction confidence; `cue_findings` has no per-item
  confidence to weight by. Same formula, one input the rules stage cannot supply.
  The `METHODS_REF` comment in `extraction.py` says so, so the divergence is now
  readable from the register rather than only from the code.
- **A part-worth traces to the whole choice set, not to one choice.** T10 fits a
  joint logit where every choice contributes to every coefficient; per-coefficient
  row lists would be fabricated attribution.
- **T43's `outside_lookup` refusal lives in the decline ledger**, not as an eleventh
  pinned constraint field. The task says `constraints.json`, and declines surface
  there only for T24's pinned ten; adding one is T24's vocabulary to change.
- **T43 ships no finder.** What to look up and under whose robots.txt is a connector
  question (`integral.robots`), and a default finder would be a network call hidden
  inside a scoring path.
- **`lifecycle.transition` still accepts a `reason` that never reaches the log.**
  That was T21's owed decision (T28's review, PR #27) and it is **accepted and
  counted**, not forbidden: refusing the reason would delete §7.1's own record of
  why an offer moved, and routing through the wrapper only would import the profile
  store into `lifecycle`, which is the coupling S5 drew its line to prevent. A
  bypass is now a number in `feedback_traceability` rather than a silence.

## Worktrees to clean up

`~/dev/js-t22-wt`, `js-t19-wt`, `js-t44-wt`, `js-t21-wt`, `js-d17-wt` — all merged,
safe to remove. `js-t43-wt` holds #145, keep until it lands. `js-night-base` is a
detached checkout of `origin/main` used only to read the board; delete any time.

**Do not work in the primary checkout** (the clone without a `-wt` suffix). The other session
lives there and the branch moves under you. Cut a worktree off `origin/main` per task.
