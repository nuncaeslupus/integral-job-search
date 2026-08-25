# Session handover — 2026-08-26, two rounds labelled, T15 reopened, spec v3 seeded

`main` clean and green, **no open PRs**. Seven PRs merged (#194–#200). Board: 107
tasks — **open 6**, claimed 0, merged 98, done 1, cancelled 2. Nothing flagged.

claude-arsenal is at **v2.4.21**; `check_update.sh` reports current.

## The numbers

| gate | threshold | now | was this morning |
|---|---|---|---|
| `extraction_macro_f1` | ≥ 0.75 | **0.4943** over 11 dimensions, n=161 | `null` |
| `prefilter_suppressed_positives` | == 0 | **2 / 209** | 0 / 40 |
| `extraction_negation_recall` | ≥ 0.80 | 6/9 hits, `unmeasured` | 2/9, `unmeasured` |
| `ontology_hit_rate` | ≥ 0.85 | 0.6168 (untouched) | 0.6168 |

**0.5539 → 0.4943 is not a regression.** The macro went from five dimensions to
eleven and n from 52 to 161; the six that entered are where the extractor is worst.
`seniority_expectation` 0.3077 → 0.6061 and `remote_arrangement` 0.5714 → 0.6957 on
doubled n; `compensation_transparency` 0.8235 → 0.6452, which is what a ten-label
estimate does when it meets twenty. `team_autonomy` is **0.0000 over 10 labels**
(0 tp, 0 fp, 10 fn) and `product_vs_services` 0.1667 — those two are the next thing
to look at, and they are cue-coverage failures, not scoring failures.

## T15 is reopened, and this is the important thing to understand

`lo-25b1` is out of `_history/`, `status: open`, issue **#52 reopened**.
`prefilter_suppressed_positives == 0` no longer holds and `verify_gates.py` says so
— 99 terminal tasks now, not 100.

**Do not close it by tuning cues.** Both suppressions are adverts carrying evidence
at *both poles* of a bipolar dimension where the cue set has vocabulary for one:

* `manfred-8360/process_formality` — "se huye de los *sprints* infinitos… Funcionan
  con **Kanban**". Person -0.6, cues +0.5.
* `tecnoempleo-5daa18bff2393309c941/stack_modernity` — Kubernetes and cloud **and**
  "Experiencia sólida en JBoss / JBoss EAP". Person -0.7, cues +0.53.

One structural cause was found and fixed: `process_formality` was bipolar with a
declared -0.6 rung and **zero negative-pole cues in any language**. Provable from
the cue set alone. Cues written from the rung's own `tell` were added, and they do
**not** resolve `manfred-8360` — it phrases its rejection with a verb `_NEGATORS`
does not carry. Extending the negator list to match one advert, or picking
legacy-stack vocabulary by reading an evaluation-split miss, is D-2's failure in a
new costume. **`== 0` was set when four adverts were labelled; at thirty-three it
is a rate with no denominator. That threshold needs a decision, not a patch.**

The regression signal did not go away. `_main` prints suppressions and exits 0 so
`make evidence` is not blocked repo-wide, and `test_prefilter` names the exact two —
a **third** suppression fails the suite.

## `mission_alignment` is narrowed — the owner's finding, and it was right

Its definition read "how much the stated purpose matters **to the candidate**",
which describes a weight, not an advert. The `-0.7` "a sector to refuse" rung was
the same error in the levels: an advert states a *sector*; whether that is a draw or
a refusal is the candidate's. `sanidad → +0.7` and `sector defensa → -0.7` put one
person's ethics in the extractor.

Now **unipolar, two rungs** — "not stated" / "purpose stated". Refusal belongs to
the candidate's weights and step 2's knockouts. Eleven suggestion marks proposing
the dead rung were dropped rather than converted.

**This is a template, not a one-off.** Any dimension whose definition says "matters
to the candidate" is suspect. `ambition`, `creativity`, `learning_orientation` and
`spare_time_engagement` are already `side: candidate_trait`; `mission_alignment` was
the only `matched` one carrying a candidate judgement, but the check is worth
repeating when T57 adds dimensions.

## Labelling: two rounds done, the tooling generalised

* **Round 1** — 11 adverts, 5 dimensions, 76 labels.
* **Round 2** — 18 adverts, 6 dimensions, 127 labels.
* 231 labels in the store, 206 on the evaluation split, 33 adverts labelled.

`make labelling-round ROUND=NN DIMENSIONS=a,b,c` builds the page;
`tools/labelling_round.py --dimensions below-floor` reports what labelling cannot
fix. **Round 3 would be 30 adverts for 6 more dimensions**, and eight cannot be
floored at all: `on_call_load` (short 7), `social_intensity` (7), `company_stage`
(5), `mission_alignment` (5), `inclusion_commitment` (4), `mentoring_culture` (4),
`career_progression` (3), `technical_depth` (1).

**The import refuses same-dimension marks with different values, and it was right
to.** T57's read pass proposes two marks for one dimension and both quotes are
true — "Modalidad híbrida (60 de teletrabajo)" *and* "Centro de trabajo Barcelona".
A `Label` holds one value with several spans. Round 2 was merged strongest-value,
all spans kept, on the owner's instruction. Expect this again; consider making the
page reconcile it rather than the importer refuse it.

## The 141 collected adverts, still parked

`tools/collect_ads.py --target-es 140 --target-en 60 --target-ca 110 --target-family 30`
takes the raw corpus 208 → 349. **Deliberately not merged**: `blind_control` is
derived from ad ids with `count = ceil(len(slice) * share)`, so growing the corpus
recomputes the cohort, invalidates the declared one, and `validate_suggestions`
then refuses to build any page. Every new advert also needs T57's read pass before
it is cheap to label. Re-run the command to reproduce it.

Those eight unfloorable dimensions, and T59's tenth negated label, are the whole
case for landing it.

## Upstream — all five findings fixed

`claude-arsenal#237` and `#239` (four findings) shipped as v2.4.17–v2.4.21 (#238,
#240, #241, #242, #243) and this repo is on v2.4.21.

**`claude-arsenal#244` is open** with two gaps in those fixes, both verified:
`check_update.sh`'s skew probe uses `find … | head -1` — unsorted and unanchored, so
another skill matching first makes the guard fail **open** and silently, the exact
property #237 was filed about; and `open_task_pr.sh`'s `git rev-parse … || pwd`
means that outside a repository the gates run against arbitrary files. Neither bites
this repo's layout today.

## Next session

1. **`team_autonomy` 0.0000 and `product_vs_services` 0.1667** are the loudest
   signals in the evidence file. Diagnose from the **cue set and the elicitation
   split** — not from evaluation misses.
2. **T15's threshold needs the owner's decision** — rate, or accept and name.
3. **T57 closes by adding dimensions**: credentials (83 unmapped concepts), pay
   structure (54), place/mobility (41), working-time shape (37).
4. **T20 and T69 are PARKED** — 2026-08-25, by the owner: deferred, not abandoned.
   Both already carry `requires: [surface:human]`, which *is* the parking mechanism —
   no worker surface declares that capability, so `task_select.py` never offers them
   and only a person can start them. Do **not** close their issues or add
   `arsenal:cancelled`: upstream reads a closed task issue as `done` and would
   release everything downstream. They resume when the owner says so.
   (`tools/blind_ranking_page.py` is T20's surface; T69 needs the exhaustion signal
   watched on a live cycle.)
5. **Spec v3 is in flight on `feat/spec-v3-silent-success-seed`** — 17 new task
   files, none with an issue handle yet, because the queue workflow cannot run while
   Actions is out of runner minutes. Create them with `handle_sync.py` when that
   branch lands. Nothing above is superseded by it.
5. Round 3 (30 adverts) whenever there is an evening for it.


---

## Spec v3 landed, and the queue is ready — 2026-08-26

**#201 and #202 are merged. No open PRs. `main` clean and green.** Board: 124 tasks —
open 15, claimed 0, blocked 8, merged 98. All 17 spec-v3 task files now carry issue
handles (**#203–#219**), created by hand because the queue workflow cannot run while
Actions has no runner minutes. `task_select.py` returns **T85** first, as the
specification intends.

### What #201's review actually found

Fourteen inline findings, and **most were stale or wrong** — that batch predated the
branch's merge commit and was reading an older tree. Verified one by one rather than
taken on trust:

* **Real, and the deepest thing in the increment.** All sixteen gates assert a
  violation count of zero, and an empty input set produces zero too — each could
  pass without evaluating a single offer, verdict, document or technique. That is
  this specification's own thesis reproduced inside its acceptance criteria. A
  second assertion in the gate block is impossible (line 1 of a `gate` fence *is*
  the gate), so all sixteen now carry **`status-key: gate_status`**, and each task
  requires its module to record the evaluated count and write
  `gate_status: "unmeasured"` when it is zero. `gate_evidence.py` then exits 3 —
  not a pass, not a fail. Same machinery `lo-6f53` uses.
* **Real, small:** the Option comparison table said "Two additive fields" where §5
  defines three; a reader taking the table could have dropped `language_requirement`.
  And D-23's writer must be wired into `_main`, or `make evidence` never regenerates
  the file its gate names.
* **Declined as wrong on the facts:** T83's deps already cover T70–T82 and T84, and
  its own text says "do not credit upstream for T85"; the spec does not name two
  first tasks (line 227 says first is T85, line 236 says *second* is the robots
  fixture, and the same sentence explains why T85 is deliberately not a blocking
  dep); D-23 is already in the systems impact table; the fence tag and blockquote
  already read correctly.

### T15's gate now separates soundness from coverage

`prefilter_suppressed_positives` was counting two different failures as one. Split
on **did any cue match inside the span the labeller cited?** Yes → the stage read
the right words and got the sign wrong (T15's). No → nothing reaches that text, so
the stage never saw it (T57's `ontology_hit_rate`), recorded as
`prefilter_uncovered_positives`.

Defined before it was measured, and it did **not** make the gate green: **1 / 209**.
`manfred-8360/process_formality` is the survivor — the `sprint` cue matches inside
"se huye de los *sprints* infinitos" and resolves to +0.5, because the rejection is
phrased with a verb `_NEGATORS` does not carry. **Do not close it by adding "huye
de"** — that advert is evaluation-split, and choosing negator vocabulary by reading
it is training on the test set. The general question belongs with T59: negation here
is carried by **verbs of rejection**, not only the three negator words per language.

Review caught a real bug in that split, since fixed: the helper matched cues against
the store's **raw** text while `cue_findings` matches NFC output, so a decomposed
cited span would have misfiled a soundness failure as coverage. Sliced then
normalised, with a regression test.

### Two sessions shared this checkout, and it cost time

Branches were switched under each other twice, and a `git add -A` swept 17 of the
other session's uncommitted files into a commit whose message described only mine.
Nothing was lost. **Work in a linked worktree, and stage explicit paths.** That
session has since ended.
