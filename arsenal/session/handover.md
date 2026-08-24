# Session handover — 2026-08-24, overnight batch (closed out in the morning)

## The queue is clear and nothing is waiting on a review

**Eight tasks merged.** The only PR open is the one carrying this handover.
The board reads
**96 tasks — open 6, claimed 0, done 1, cancelled 2, merged 87**, and **none of
the six open tasks is blocked**: every dependency they name is merged.

| PR | Task | Gate | Issue |
|---|---|---|---|
| #140 | T22 `methods_ref` link check, both directions | `undocumented_methods == 0` | 54 |
| #141 | T19 explanations citing the advert | `explained_fraction == 1.0` | 58 |
| #142 | T44 the offer card as a filled template | `provisional_rankings_unlabelled == 0` | 66 |
| #144 | D-17 the card renders the stored link | `ranked_offers_without_a_url == 0` | 98 |
| #143 | T21 the feedback loop | `feedback_traceability == 1.0` | 60 |
| #145 | T43 outside-the-advert enrichment | `outside_source_spans_in_explanations == 0` | 65 |
| #148 | T26 cancelled, T26b split out | — (T26b carries `trait_dimensions_ready >= 4`) | closed 53 |

Steps 9 (`ranking`) and 10 (`feedback`) both flipped to `implemented` in
`spec-v2-steps.json`. T48's drift check and `step_certification` each caught
that on their own — neither needed noticing.

## What is open, and what it needs

Six tasks, all unblocked. Five an agent can take; one is yours.

| task | id | note |
|---|---|---|
| **T20** | `lo-c48f` | **`[HUMAN]` — this one is yours.** A blind manual ranking of 20 held-out ads. Deps satisfied; nothing else waits on it. |
| T56 | `lo-6f53` | `extraction_macro_f1 >= 0.75` once the label floor is met |
| T57 | `lo-7c14` | `ontology_hit_rate >= 0.85` — also what makes T26's old gate measurable |
| T59 | `lo-4b17` | `extraction_negation_recall >= 0.80` — what `task_select` offers next |
| T26b | `t-1956a8c6` | the four candidate-trait dimensions (new, see below) — issue **#147**, open because the task is |
| D-19 | `t-e6546af7` | the dimension model is software-only — 0 of 25 settled on construction |

T56, T57 and T59 all wait on **labelled data volume**, not on each other. They
are the three that will actually pace M4.

## T26 is cancelled; T26b carries the buildable half

You asked for the split. Job (2) — the four candidate-trait dimensions
(creativity, ambition, learning orientation, spare-time engagement),
`side: candidate_trait`, no cues, elicited only — is now **T26b**
(`t-1956a8c6`, issue #147), gated on `trait_dimensions_ready >= 4`. That number
counts the dimensions that are *complete* (rungs, three-language labels, an
elicitation question), not the ones that exist: T26's own scope note says a
dimension without rungs has no class set for anything to score.

T26 (#53) is closed as not planned, archived with `status: cancelled` and
`split-into: t-1956a8c6`. Job (1) — widening the matched dimensions by corpus
sweep — was retired by your 2026-08-19 scope change, and T26's gate
`ontology_hit_rate >= 0.85` was **T57's own metric**, so the task could never
have been measured from inside itself.

**Four tasks had to be edited in the same change, and this is the part worth
checking.** `cancelled` is *not* terminal in `task_select.py`
(`TERMINAL = {"done", "merged"}`), so T56, T57, T59 and D-19 would have waited
on T26 forever. Their `deps` drop it, each with a note on why nothing is lost —
T57's was circular, T56/T59 wait on the label floor rather than on the model's
breadth, and D-19 arguably replaces T26's retired half by asking whether to
widen at all. If you disagree with any one of those four, that is the decision
to revisit; the cancellation itself is cheap to undo, the dependency edits are
the judgement call.

## Two things the reviews caught that were mine

Eighteen findings across seven PRs: fourteen fixed, four declined with reasoning
posted to the PR. Two are worth your attention because they were errors of
mine, not of the code under review:

- **I called `lo-1af2` "T23" in four places.** It is **T25**; T23 is `lo-680d`.
  Worse, `status/plan.md` already declared T26b's Depends as T23 while the task
  file declared **no deps at all** — the graph was missing an edge the plan
  asserts. Fixed in #148.
- **`render()` could not pass outside findings to `card()`** (#145). The card
  grew a block for them and the page function never supplied one, so the only
  way to see a finding was to call `card()` directly, which nothing but the
  tests does. T43's whole claim is that the candidate can tell an employer's
  words from a review site's — and on the page, they could not see either.

The four declines, each answered on its PR: regenerating the ranking artifact
after `record_decision` (that is step 9's inputs, not step 10's); labelling L2
pages provisional (reads the objective backwards); removing arsenal template
text from one archived task file out of the 15 that carry it; and replacing
T43's structural provenance guarantee with a flag on the shared span contract.

## Filed upstream against claude-arsenal

- **[#210](https://github.com/nuncaeslupus/claude-arsenal/issues/210)** —
  `bin/rebase_stack.sh` cannot complete on a repo with evidence gates. It runs
  `git rebase --onto` and force-pushes with nothing in between, so it stops on
  the evidence conflict every rebase produces here. Arsenal can fix this
  generically: it knows the evidence paths from each task's `evidence:` gate key
  and the regenerate command from the `host-gate` config key. It also
  force-pushes *without* running the gate, so a clean rebase can publish a head
  that fails the host's own drift check.
- **[#211](https://github.com/nuncaeslupus/claude-arsenal/issues/211)** —
  `new_task.py` rejects a dep on merged work: `existing_ids` globs
  `arsenal/tasks/*.md` non-recursively and never sees `_history/`. This is not
  hypothetical — it is why T26b shipped without its dep on T23 and needed #148's
  follow-up commit to get it back. `task_select.py` reads `_history/`
  deliberately, so the two views of "which tasks exist" disagree.

I did not adopt `tmp/regate.sh` upstream as written: it hardcodes
`status/evidence/` and `make host-gate`, so it is ours, not shareable. It stays
untracked in `tmp/`. It resolves a rebase conflicting **only** on
`status/evidence/*.json` by regenerating rather than merging — those files are
build products, so the right answer is whatever the code measures on the
resulting tree — and refuses if anything else is conflicted. It ran seven times
across the night, including on #145's final rebase.

## Environment

- **CI is still out of runner minutes.** Every job fails in ~5s with
  `runner_id: 0` and an empty `runner_name`. Red CI said nothing about any of
  these branches; `make host-gate` locally is the real gate and every one passed
  it before merging.
- **CodeRabbit's included reviews are 10 per hour.** It ran out partway through
  the night, which is the only reason #145 sat unmerged until morning. The quota
  recovered at ~08:30 and #145 got its first review then.
- **The arsenal bundle is v2.2.1**; `check_update.sh --check-only` reports
  **v2.2.2 available**. Not taken — worth doing deliberately, since #210 and
  #211 are both filed against it.
- **The other session merged #133, #138, #139 and #135** mid-run, which is why
  the stack was rebased after each.

## Stated ceilings from the merged work

- **`hours` and `contract` can only ever render `unknown`** on the offer card.
  Step 9 lists them among the bullets and §5.2's normalised offer has no field
  for either, so no connector can supply one. Making the card say more is a
  change to the offer contract — worth its own task.
- **§4.1 is implemented as an unweighted mean.** The register weights the
  dimension score by extraction confidence; `cue_findings` has no per-item
  confidence to weight by. The `METHODS_REF` comment in `extraction.py` says so.
- **A part-worth traces to the whole choice set, not to one choice.** T10 fits a
  joint logit; per-coefficient row lists would be fabricated attribution.
- **T43 ships no finder.** What to look up, and under whose robots.txt, is a
  connector question (`integral.robots`); a default finder would be a network
  call hidden inside a scoring path. So `outside_source_spans` has exactly one
  producer today — the fixture.
- **T43's `outside_lookup` refusal lives in the decline ledger**, not as an
  eleventh pinned constraint field. Adding one is T24's vocabulary to change.
- **`lifecycle.transition` still accepts a `reason` that never reaches the
  log.** Accepted and *counted*, not forbidden: refusing it would delete §7.1's
  record of why an offer moved, and routing through the wrapper only would
  import the profile store into `lifecycle`, the coupling S5 drew its line to
  prevent. A bypass is a number in `feedback_traceability` rather than a
  silence.
- **Landing T26b will break `test_the_committed_model_is_all_matched_and_unchanged`
  correctly.** It asserts `{d.side for d in dimensions} == {"matched"}`, a claim
  about a model that had no trait dimensions yet. The task says to update it to
  assert the sides present, not to delete it.

## Worktrees

Every branch below is merged, so all three are safe to remove:

- `~/dev/js-t26-wt` — #148, and the branch this handover was written on
- `~/dev/js-t43-wt` — #145
- `~/dev/js-night-base` — never held a branch; a detached checkout of
  `origin/main` used only to read the board, so it is stale the moment
  anything merges. Re-cut it rather than pulling it.

`~/dev/job-search-t25-wt` and `~/dev/job-search-arsenal-queue-wt` are **not
mine** — leave them to the other session.

**Do not work in the primary checkout** (the clone without a `-wt` suffix). The
other session lives there and the branch moves under you. Cut a worktree off
`origin/main` per task.
