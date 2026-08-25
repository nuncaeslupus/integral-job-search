# The labelling round, directed — a proposal

Written 2026-08-25 for the owner's review. **Nothing here has been started.** The
question this answers is the one the owner asked: how to spend the least human time
for the most gate value, rather than grinding 236 labels and finding out afterwards
whether it was useful.

Companion to `corpus/labelled/README.md`, which costed the round on 2026-08-24 and
found the one action serving two tasks. This adds the ordering, the hazard that
ordering avoids, and where a subset is honest.

---

## 1. The hazard: labelling first breaks the build

`integral/extraction.py`, in `measure()`:

```python
if scorable:  # pragma: no cover - unreachable until the corpus grows
    raise ExtractionError(
        "dimensions are now above the label floor, so extraction_macro_f1 is "
        f"measurable for {scorable} — this branch is a placeholder and scoring "
        "must be implemented before it can report a number (T20/T26)"
    )
```

`scorable` is every ad-side dimension with **≥10** evaluation labels. Today every
dimension has exactly **1**, so the set is empty and the branch never runs.

**The tenth label on any single dimension stops every task PR in the repo being
openable.** The chain is worth stating exactly, because the failure is an unhandled
exception rather than a measured shortfall: `measure()` raises, so
`python -m integral.extraction` exits non-zero, so `make evidence` prints
`GATE FAILED` and exits 1, so `make host-gate` fails — and `open_task_pr.sh` runs
`make host-gate` as a hard precondition, so no task PR opens at all. A round that
starts by labelling would discover this at label ten, with nine already spent.

**So the scoring lands first, and it is code, not labels.** It can be written and
tested against fixtures today, with no corpus work at all: the floor is a constant
and a fixture store can carry ten synthetic labels. No human is needed for this step,
and it is the only ordering constraint in the whole plan.

---

## 2. T57 needs no human labelling at all

This is the part most worth knowing before committing anyone's evening.

`ontology_hit_rate = mapped / (mapped + unmapped)`. It reads
`corpus/labelled/suggestions.json`, and is `unmeasured` today because that file has
no top-level `unmapped` key — no committed source declares it *could* have recorded
a concept it failed to map. Today's `828 concepts read, 0 unmapped` is a property of
the 2026-08-19 briefing, which worked "from each dimension's definition and its named
rungs only". That is precisely what T57 refuses to accept as a source.

**One machine pass fixes it**: re-read all **208** raw ads with a *meaning-first*
briefing — name concepts freely, map to dimensions afterwards, and record whatever
fails to map. That pass produces the `unmapped` key, and `ontology_hit_rate` becomes
measurable the moment it lands.

It is an LLM read over 208 adverts — a cost, and the owner's to approve — but it is
**machine time, not human time**, and it is the single highest-value action in this
document. It also pre-marks the 108 ads that carry no marks (see §3).

---

## 3. T56: the subset is where the direction lives

236 labels short of full coverage — **14 dimensions hold one label each and eleven
hold none**, so it is `14 × 9 + 11 × 10`, not `25 × 9`. That is the number that
makes the round feel pointless, and it is avoidable, because the gate does not require
full coverage.

`extraction_macro_f1` is a **macro average over the scorable dimensions** — those at
or above the floor. Floor five dimensions and the score is the mean over those five.
So the round's size is a choice, and the choice is:

| Dimensions floored | Labels needed (10 each, minus the 1 already held) | Round size |
|---|---|---|
| 5 | ~45 | an evening |
| 10 | ~90 | a weekend |
| 25 (all) | 236 | the thing already declined |

**The trap, stated plainly:** choosing dimensions because they are *easy to label*
games the score. A macro over five dimensions picked for cheapness says nothing about
extraction quality, and it would pass a gate while measuring the selection. So:

- **Choose by product centrality, not by ease.** The dimension model exists so that
  non-skill dimensions survive to the ranking; the ones to floor are the ones a
  ranking actually leans on. `remote_arrangement` is the spec's own running example
  ("this candidate weights remote arrangement above pay").
- **Declare the subset and its coverage beside the score.** `T15.json` already carries
  `scorable_dimensions` and `dimensions_below_floor`, so the honesty is already
  reportable — it just has to be read as part of the result rather than ignored.
- **Never widen the subset after seeing the score.** Picking again once a number is
  known is the same failure as cue-derived gold (D-2). Fix the list first.

A proposed five, for the owner to accept or replace — frequency in the corpus is a
tiebreak, never the criterion:

`remote_arrangement`, `compensation_transparency`, `contract_stability`,
`schedule_flexibility`, `seniority_expectation`.

### Decided — 2026-08-25, before the first label of the round

The owner accepted those five unchanged. **The subset is now closed**: no dimension
joins or leaves it on the strength of a score, because the whole reason it was picked
cold is that picking again with a number in hand is D-2's failure wearing a different
hat. If five turns out to be the wrong size, the honest move is to say so *and start
over*, not to widen.

What this commits the round to:

* `extraction_macro_f1` is the mean over **exactly these five**, and the twenty
  others stay in `dimensions_below_floor` where `T15.json` already names them.
  A reader who quotes the score without that list is quoting a mean over a fifth
  of the model.
* **The declared subset and the measured subset are not the same list, and both
  are reported.** A dimension can clear the floor with ten labels and still sit
  outside the macro, because F1 needs a positive class: ten class-0 labels assert
  nothing to score. `T15.json` names the declared five, `extraction_scored_dimensions`
  names what the mean actually covered, and `dimensions_without_positives` names the
  gap between them. If that gap ever swallows all five, the aggregate stays
  `unmeasured` — which is the honest answer and not a failure of the round.
* ~45 labels, ten per dimension minus the one each already holds — and every one
  is a confirm-and-move rather than a blind read, because T57's re-seed pre-marked
  all 176 non-control ads.
* `collaboration_mode` is **out**, and stays out for this round. Not because it is
  unfindable — that inference would come from cue firings, which are the thing the
  labels are meant to judge — but because it is the one dimension with no pre-mark,
  so it is the only one whose labels cost a blind read each. Establish its
  prevalence first, in a round of its own.

The scorer these labels feed is in place as of this round's start: `measure()` no
longer raises when a dimension crosses the floor, so label ten does not break
`make host-gate` for the repo.

**`collaboration_mode` is the expensive one, for a reason worth stating carefully.**
It is the only dimension with no pre-mark even inside the 84, so every label for it is
a blind read rather than a confirmation. What is *not* established is that ten
positives are unfindable: its cues fire on 7 of 208 ads, but inferring gold scarcity
from cue firings is the cue-derived reasoning D-2 exists to refuse — the cues are what
the labels are meant to judge. Treat it as costly, not as impossible, and if it is
wanted in the subset, establish its prevalence first.

---

## 4. T59 is the cheapest gate here — do it first among the human work

`negated_label_count: 2`, floor **10**. **Eight labels**, not 236.

And they are targetable rather than searched for by hand: the negation machinery
already fires — `negation_firings_count: 4`, `negation_window_only_count: 2` — so the
cue pass can shortlist the ads carrying a negator and the human confirms perhaps
fifteen to bank ten. That is under an hour, and it closes `extraction_negation_recall`
outright.

If only one thing in this document gets done, it should be this.

---

## 5. The order

| # | Step | Who | Unblocks |
|---|---|---|---|
| 1 | Implement macro-F1 scoring behind the placeholder, fixture-tested | agent | nothing yet — **prevents** the build breaking at label ten |
| 2 | Regenerate `suggestions.json` over 208 ads, meaning-first, emitting `unmapped` | machine pass, owner approves the spend | **T57 outright**; pre-marks 108 ads for step 4 |
| 3 | Confirm ~15 negation shortlist entries to bank 10 negated labels | human, <1h | **T59** |
| 4 | Confirm-and-move a declared subset of dimensions to floor | human, sized by §3 | **T56** |

Steps 2, 3 and 4 are independent of each other once step 1 exists. Step 1 blocks
nothing except the safety of steps 3 and 4.

**A pre-mark is not a label.** Step 2 shortens the round by turning blind reads into
confirm-and-move; it does not stand in for the person at the end of it.

---

## 6. What is deliberately not proposed

- **Lowering the floor of 10.** It is `MIN_EVALUATION_LABELS_PER_DIMENSION`, and a
  denominator chosen to fit the labels on hand measures the labelling, not the
  extractor.
- **Machine-generated labels as gold.** D-2 named this: cue-derived gold scores the
  cues. The pre-marking is a starting point for a person, never the answer.
- **T26 as a prerequisite.** T57's body still cites it; **T26 is cancelled** and T26b
  shipped the four candidate-trait dimensions in its place (#158). That reference
  wants correcting whenever T57 is next touched — it is stale, not load-bearing.
